#!/usr/bin/env python3
"""Flash/RAM budget and float-helper audit for MOSAIC firmware builds.

Reads the ELF and linker map of each executable and prints a Markdown report.
Two build layouts are understood: the Pico SDK's CMake build (firmware/) and
the course's micro T-Kernel template, built with make in node/build_make.

* flash and RAM used, from the linker's own boundary symbols;
* which part of the build the bytes belong to (our code, micro T-Kernel, Wi-Fi
  driver, lwIP, USB, FreeRTOS, Pico SDK, C library), from the map file;
* the largest RAM users, since RAM is the scarce resource on the RP2040;
* every place our own code calls a software floating-point helper or a libm
  function, by function name, so the CSC21 "no floats in the processing path"
  claim can be checked against the build rather than the source.

Standard library only. Usage, after building the firmware:

    python3 firmware/tools/fw_budget.py firmware/build --out budget.md
    python3 firmware/tools/fw_budget.py node/build_make --out budget.md

The toolchain is found from the build's CMakeCache.txt; pass --tool-prefix to
override (for example /path/to/bin/arm-none-eabi-).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

FIRMWARE_DIR = Path(__file__).resolve().parent.parent

# RP2040 on a Pico W: 2 MB QSPI flash, 256 KB main SRAM + 2 x 4 KB scratch banks.
FLASH_BASE, FLASH_SIZE = 0x10000000, 2 * 1024 * 1024
RAM_BASE, RAM_MAIN_SIZE, RAM_TOTAL_SIZE = 0x20000000, 256 * 1024, 264 * 1024

DEFAULT_ELFS = (
    "node/mosaic_node.elf",
    "node/mosaic_node_rtos.elf",
    "audio/audio_talking.elf",
    "audio/audio_benchmark.elf",
)

# Software float/double helpers the compiler emits on a Cortex-M0+ (no FPU),
# plus the libm functions our code could call directly.
FLOAT_HELPER = re.compile(
    r"^(__aeabi_[fd][a-z0-9]+|__aeabi_u?[il]2[fd]"
    r"|(sqrt|cbrt|log|log10|log2|log1p|exp|exp2|expm1|pow|sin|cos|tan|asin|acos|atan|atan2"
    r"|sinh|cosh|tanh|floor|ceil|round|lround|lrint|rint|trunc|fmod|fabs|hypot)f?)$"
)

COMPONENTS = ("Our code", "micro T-Kernel and BSP", "Wi-Fi driver (CYW43)", "lwIP", "USB (TinyUSB)",
              "FreeRTOS", "Pico SDK", "C library and compiler")

INPUT_SECTION = re.compile(r"^ (\.\S+|COMMON)(?:\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*))?$")
INPUT_SECTION_CONT = re.compile(r"^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$")


@dataclass
class Placed:
    section: str  # input section name, e.g. .bss.audio_buffer
    addr: int
    size: int
    source: str  # object file or archive(member), as the map prints it


@dataclass
class Breakdown:
    flash: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COMPONENTS, 0))
    ram: dict[str, int] = field(default_factory=lambda: dict.fromkeys(COMPONENTS, 0))
    ram_items: list[Placed] = field(default_factory=list)


def parse_map(text: str) -> list[Placed]:
    """Input sections the linker placed in flash or RAM (discarded ones have address 0)."""
    start = text.find("Linker script and memory map")
    lines = text[start:].splitlines() if start >= 0 else []
    placed: list[Placed] = []
    pending: str | None = None
    for line in lines:
        m = INPUT_SECTION.match(line)
        if m:
            name, addr, size, source = m.groups()
            if addr is None:
                pending = name  # address, size and file follow on the next line
                continue
            pending = None
        elif pending:
            c = INPUT_SECTION_CONT.match(line)
            if not c:
                pending = None
                continue
            name, (addr, size, source) = pending, c.groups()
            pending = None
        else:
            continue
        a, s = int(addr, 16), int(size, 16)
        if s and (FLASH_BASE <= a < FLASH_BASE + FLASH_SIZE or RAM_BASE <= a < RAM_BASE + RAM_TOTAL_SIZE):
            placed.append(Placed(name, a, s, source.strip()))
    return placed


def source_file(obj: str, build_dir: Path, firmware_dir: Path = FIRMWARE_DIR) -> Path | None:
    """The firmware/ source file an object came from, or None if it isn't ours.

    CMake names objects <subdir>/CMakeFiles/<target>.dir/<relative source>.o and
    archive members <subdir>/lib<x>.a(<file>.o); SDK sources keep their absolute
    path under <target>.dir/, so they never resolve inside firmware/.
    The template build names objects ./mtkernel_3/<path under node/>.o; only
    app_program/ is ours, the rest is the template's kernel, BSP and drivers.
    """
    m = re.match(r"^(?:\./)?mtkernel_3/(app_program/.+)\.o$", obj)
    if m:
        for ext in (".c", ".S", ".s"):
            candidate = build_dir.parent / (m.group(1) + ext)
            if candidate.is_file():
                return candidate
        return None
    m = re.match(r"^(.*)\.a\((.+)\.o(?:bj)?\)$", obj)
    if m:
        archive, member = m.groups()
        rel_dir = Path(archive).parent
        candidate = firmware_dir / _relative(rel_dir, build_dir) / member
        return candidate if candidate.is_file() else None
    m = re.match(r"^(.*)/CMakeFiles/[^/]+\.dir/(.+)\.o(?:bj)?$", obj)
    if m:
        subdir, rel = m.groups()
        candidate = firmware_dir / _relative(Path(subdir), build_dir) / rel
        return candidate if candidate.is_file() else None
    return None


def _relative(path: Path, build_dir: Path) -> Path:
    if path.is_absolute():
        try:
            return path.relative_to(build_dir)
        except ValueError:
            return Path("__outside__")
    return path


def component(obj: str, build_dir: Path) -> str:
    if source_file(obj, build_dir):
        return "Our code"
    low = obj.lower()
    if re.match(r"^(?:\./)?mtkernel_3/", obj):       # course template build
        if "tinyusb" in low:
            return "USB (TinyUSB)"
        if "cyw43" in low or "libwifi" in low:
            return "Wi-Fi driver (CYW43)"
        if "lwip" in low:
            return "lwIP"
        return "micro T-Kernel and BSP"
    if "cyw43" in low:
        return "Wi-Fi driver (CYW43)"
    if "/lwip/" in low or "pico_lwip" in low:
        return "lwIP"
    if "freertos" in low:
        return "FreeRTOS"
    if re.search(r"lib(c|c_nano|g|gcc|m|nosys|stdc\+\+)[^/]*\.a\(", low) or "/arm-none-eabi/" in low:
        return "C library and compiler"
    return "Pico SDK"


def breakdown(placed: list[Placed], build_dir: Path) -> Breakdown:
    b = Breakdown()
    for p in placed:
        if p.section in (".heap", ".stack"):
            continue  # reservations, reported separately as heap and stack space
        comp = component(p.source, build_dir)
        if p.addr >= RAM_BASE:
            b.ram[comp] += p.size
            b.ram_items.append(p)
            if p.section.startswith(".data") or p.section.startswith(".time_critical"):
                b.flash[comp] += p.size  # initial values are stored in flash and copied at boot
        else:
            b.flash[comp] += p.size
    return b


# ---------------------------------------------------------------- toolchain


def run(cmd: list[str]) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def tool_prefix(build_dir: Path) -> str:
    cache = build_dir / "CMakeCache.txt"
    if cache.is_file():
        m = re.search(r"^CMAKE_C_COMPILER:\w+=(.+gcc)(\.exe)?$", cache.read_text(errors="replace"), re.M)
        if m:
            return m.group(1)[: -len("gcc")]
    return "arm-none-eabi-"


def linker_symbols(prefix: str, elf: Path) -> dict[str, int]:
    syms = {}
    for line in run([prefix + "nm", str(elf)]).splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def float_calls(prefix: str, obj_path: str, build_dir: Path) -> dict[str, set[str]]:
    """function -> float helpers it calls, from relocations in one of our objects."""
    m = re.match(r"^(.*\.a)\((.+)\)$", obj_path)
    target = build_dir / (m.group(1) if m else obj_path)
    out = run([prefix + "objdump", "-dr", str(target)])
    calls: dict[str, set[str]] = {}
    member_ok = m is None
    fn = "?"
    for line in out.splitlines():
        if m and line.endswith("file format elf32-littlearm"):
            member_ok = line.split(":")[0].strip() == m.group(2)
            continue
        if not member_ok:
            continue
        f = re.match(r"^[0-9a-f]+ <(.+)>:$", line)
        if f:
            fn = f.group(1)
            continue
        r = re.search(r"R_ARM_\w+\s+(\S+)$", line)
        if r and FLOAT_HELPER.match(r.group(1)):
            calls.setdefault(fn, set()).add(r.group(1))
    return calls


def versions(build_dir: Path, prefix: str) -> list[str]:
    rows = []
    cmake = (build_dir / "CMakeCache.txt").is_file()
    src_root, pathspec = (FIRMWARE_DIR, [".", ":!tools"]) if cmake else (build_dir.parent, ["."])
    try:
        rev = run(["git", "-C", str(src_root), "rev-parse", "--short", "HEAD"]).strip()
        dirty = run(["git", "-C", str(src_root), "status", "--porcelain", "--", *pathspec]).strip()
        rows.append(f"Firmware commit `{rev}`" + (" with uncommitted firmware changes" if dirty else ""))
    except (OSError, subprocess.CalledProcessError):
        rows.append("Firmware commit unknown (not a git checkout)")
    try:
        rows.append("Compiler " + run([prefix + "gcc", "--version"]).splitlines()[0])
    except (OSError, subprocess.CalledProcessError, IndexError):
        pass
    cache = build_dir / "CMakeCache.txt"
    sdk = None
    if cache.is_file():
        m = re.search(r"^PICO_SDK_PATH:\w+=(.+)$", cache.read_text(errors="replace"), re.M)
        sdk = m.group(1) if m else None
    else:
        sdk = os.environ.get("PICO_SDK_PATH")   # the template's make build reads it from here
    if sdk:
        ver = Path(sdk) / "pico_sdk_version.cmake"
        if ver.is_file():
            parts = dict(re.findall(r"set\(PICO_SDK_VERSION_(MAJOR|MINOR|REVISION) (\d+)\)", ver.read_text()))
            rows.append("Pico SDK {MAJOR}.{MINOR}.{REVISION}".format(**parts) if len(parts) == 3 else "Pico SDK version unknown")
    return rows


# ------------------------------------------------------------------- report


def kb(n: int) -> str:
    return f"{n / 1024:.1f} KB"


def pct(n: int, of: int) -> str:
    return f"{100 * n / of:.1f} %"


def shown(src: Path, build_dir: Path) -> str:
    """A source path for the report: relative to the repo, or to the build's
    parent folder when the build is a copy outside the repo."""
    for root in (FIRMWARE_DIR.parent, build_dir.parent.parent, build_dir.parent):
        try:
            return str(src.relative_to(root))
        except ValueError:
            continue
    return str(src)


def largest_ram(items: list[Placed], build_dir: Path, prefix: str) -> list[tuple[str, str, int]]:
    """(name, origin, bytes), biggest first. A file's generic .bss/.data section is
    split into its variables so the table names the actual buffers."""
    rows = []
    for p in items:
        src = source_file(p.source, build_dir)
        origin = shown(src, build_dir) if src else component(p.source, build_dir)
        if src and p.section in (".bss", ".data", "COMMON"):
            rows += [(name, origin, size) for name, size in object_variables(prefix, p.source, build_dir, p.section)]
        elif p.section in (".bss", ".data", ".noinit", "COMMON"):
            # a whole file's unnamed section: say which file
            obj = re.sub(r"\)$", "", p.source.rsplit("(", 1)[-1]).rsplit("/", 1)[-1]
            rows.append((f"{p.section} of {obj}", origin, p.size))
        else:
            rows.append((re.sub(r"^\.(bss|data|time_critical)\.", "", p.section), origin, p.size))
    return sorted(rows, key=lambda r: r[2], reverse=True)


def object_variables(prefix: str, obj_path: str, build_dir: Path, section: str) -> list[tuple[str, int]]:
    m = re.match(r"^(.*\.a)\((.+)\)$", obj_path)
    target = build_dir / (m.group(1) if m else obj_path)
    kinds = "bB" if section in (".bss", "COMMON") else "dD"
    found, member_ok = [], m is None
    for line in run([prefix + "nm", "-S", "-A", str(target)]).splitlines():
        head, _, rest = line.rpartition(":")
        if m:
            member_ok = head.endswith("(" + m.group(2) + ")") or head.endswith(":" + m.group(2))
        parts = rest.split()
        if member_ok and len(parts) == 4 and parts[2] in kinds:
            found.append((parts[3], int(parts[1], 16)))
    return found


def find_map(elf: Path) -> Path | None:
    """SDK 2.x writes <name>.elf.map; SDK 1.5.1 writes <name><CMAKE_EXECUTABLE_SUFFIX>.map,
    which can come out as <name>.map."""
    for candidate in (elf.with_suffix(".elf.map"), elf.with_suffix(".map")):
        if candidate.is_file():
            return candidate
    return None


def report_elf(build_dir: Path, rel: str, prefix: str) -> list[str]:
    elf = build_dir / rel
    out = [f"## `{elf.stem}`", ""]
    syms = linker_symbols(prefix, elf)
    if "__flash_binary_end" not in syms and "__data_org" in syms and "__bss_end" in syms:
        out += template_memory(syms)
    elif "__flash_binary_end" in syms:
        out += sdk_memory(prefix, elf, syms)
    else:
        out += ["Linker layout not recognised, so no memory summary.", ""]
    return out + map_report(build_dir, elf, prefix)


def template_memory(syms: dict[str, int]) -> list[str]:
    """TRON's linker script (course template): flash holds the code, then the
    .data initial values at __data_org; RAM holds .data and .bss, and the rest is
    micro T-Kernel's own memory pool (task stacks, kernel objects) plus the
    exception stack, handed out at run time, not by malloc."""
    flash_used = syms["__data_org"] + (syms["__data_end"] - syms["__data_start"]) - FLASH_BASE
    static_ram = syms["__bss_end"] - RAM_BASE
    pool = RAM_BASE + RAM_MAIN_SIZE - syms["__bss_end"]
    return [
        "| Memory | Used | Of | Share |",
        "|---|---:|---:|---:|",
        f"| Flash (program + constants + initial data) | {kb(flash_used)} | {kb(FLASH_SIZE)} | {pct(flash_used, FLASH_SIZE)} |",
        f"| RAM, static (globals, buffers, vector table) | {kb(static_ram)} | {kb(RAM_MAIN_SIZE)} | {pct(static_ram, RAM_MAIN_SIZE)} |",
        f"| RAM after that: micro T-Kernel memory pool (task stacks, kernel objects) and exception stack | {kb(pool)} | {kb(RAM_MAIN_SIZE)} | {pct(pool, RAM_MAIN_SIZE)} |",
        "",
    ]


def sdk_memory(prefix: str, elf: Path, syms: dict[str, int]) -> list[str]:
    out = []
    flash_used = syms["__flash_binary_end"] - FLASH_BASE
    static_ram = syms["end"] - RAM_BASE
    heap_free = syms["__StackLimit"] - syms["end"]  # _sbrk grows the heap from `end` up to __StackLimit (SDK 1.5 and 2.x)
    core0_stack = syms["__StackTop"] - syms["__StackOneTop"]
    core1_stack = syms["__StackOneTop"] - syms["__StackLimit"]
    out += [
        "| Memory | Used | Of | Share |",
        "|---|---:|---:|---:|",
        f"| Flash (program + constants + initial data) | {kb(flash_used)} | {kb(FLASH_SIZE)} | {pct(flash_used, FLASH_SIZE)} |",
        f"| RAM, static (globals, buffers, vector table) | {kb(static_ram)} | {kb(RAM_MAIN_SIZE)} | {pct(static_ram, RAM_MAIN_SIZE)} |",
        f"| RAM left for the C heap (`malloc`) | {kb(heap_free)} | {kb(RAM_MAIN_SIZE)} | {pct(heap_free, RAM_MAIN_SIZE)} |",
        f"| Stack space, core 0 / core 1 (scratch banks) | {kb(core0_stack)} / {kb(core1_stack)} | 4.0 KB each | |",
    ]
    if "ucHeap" in syms:
        heap_bytes = next(
            (int(line.split()[1], 16) for line in run([prefix + "nm", "-S", str(elf)]).splitlines()
             if line.endswith(" ucHeap")), 0)
        if heap_bytes:
            out.append(f"| of which FreeRTOS heap (task stacks, queues), inside static RAM | {kb(heap_bytes)} | | |")
    out.append("")
    return out


def map_report(build_dir: Path, elf: Path, prefix: str) -> list[str]:
    out = []
    map_path = find_map(elf)
    if map_path is None:
        return out + ["No linker map found, so no breakdown.", ""]
    placed = parse_map(map_path.read_text(errors="replace"))
    b = breakdown(placed, build_dir)
    out += ["| Part of the build | Flash | RAM |", "|---|---:|---:|"]
    out += [f"| {c} | {kb(b.flash[c])} | {kb(b.ram[c])} |" for c in COMPONENTS if b.flash[c] or b.ram[c]]
    out += ["", "Largest RAM users:", "", "| Item | From | Size |", "|---|---|---:|"]
    for name, origin, size in largest_ram(b.ram_items, build_dir, prefix)[:8]:
        out.append(f"| `{name}` | {origin} | {kb(size)} |")
    out.append("")

    ours = sorted({p.source for p in placed if source_file(p.source, build_dir)})
    floats: list[tuple[str, str, set[str]]] = []
    for obj in ours:
        rel_src = shown(source_file(obj, build_dir), build_dir)
        for fn, helpers in float_calls(prefix, obj, build_dir).items():
            floats.append((rel_src, fn, helpers))
    if floats:
        out += ["Floating-point calls in our code:", "", "| File | Function | Calls |", "|---|---|---|"]
        out += [f"| {f} | `{fn}` | {', '.join(sorted(h))} |" for f, fn, h in sorted(floats)]
    else:
        out.append(f"Floating-point calls in our code: none ({len(ours)} of our object files checked).")
    return out + [""]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("build_dir", type=Path)
    ap.add_argument("--elf", action="append", help="ELF path relative to build_dir (repeatable)")
    ap.add_argument("--tool-prefix", help="e.g. /opt/arm/bin/arm-none-eabi-")
    ap.add_argument("--out", type=Path, help="write the report here instead of stdout")
    args = ap.parse_args(argv)
    build_dir = args.build_dir.resolve()
    prefix = args.tool_prefix or tool_prefix(build_dir)
    elfs = (args.elf or [e for e in DEFAULT_ELFS if (build_dir / e).is_file()]
            or sorted(e.name for e in build_dir.glob("*.elf")))   # template: images sit in build_make/
    if not elfs:
        print(f"No firmware ELFs found in {build_dir}", file=sys.stderr)
        return 1
    lines = ["# Firmware resource budget (generated)", ""]
    lines += [f"- {v}" for v in versions(build_dir, prefix)]
    lines += ["", "Static numbers from the linker. Run-time use (stack high-water marks, "
              "minimum free RTOS memory, CPU load) comes from the node's serial log.", ""]
    for rel in elfs:
        lines += report_elf(build_dir, rel, prefix)
    text = "\n".join(lines)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

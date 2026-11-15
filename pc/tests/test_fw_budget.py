"""Parser tests for firmware/tools/fw_budget.py (the toolchain isn't needed)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "firmware" / "tools"))
import fw_budget  # noqa: E402

MAP = """\
Archive member included to satisfy reference by file (symbol)
 .text          0x00000000        0x0 ignored/before/the/memory/map.o

Linker script and memory map

 .text.main     0x10000280      0x128 node/CMakeFiles/mosaic_node.dir/node_main.c.o
 .text.cyw43_ll_bus_init
                0x10001000     0x2000 node/CMakeFiles/mosaic_node.dir/sdk/lib/cyw43-driver/src/cyw43_ll.c.o
 .bss.memp_memory_PBUF_POOL_base
                0x20002000     0x8f90 node/CMakeFiles/mosaic_node.dir/sdk/lib/lwip/src/core/memp.c.o
 .data.counter  0x20000100        0x4 node/CMakeFiles/mosaic_node.dir/node_main.c.o
 .bss           0x20010000     0x7d00 audio/libaudio_dsp.a(audio_dsp.c.o)
 .text.memcpy   0x10003000       0x40 /opt/arm/lib/gcc/arm-none-eabi/thumb/v6-m/libc_nano.a(lib_a-memcpy.o)
 .text.unused   0x00000000       0x80 node/CMakeFiles/mosaic_node.dir/node_main.c.o
 .heap          0x2000e6a0      0x800 node/CMakeFiles/mosaic_node.dir/sdk/src/crt0.S.o
 .debug_info    0x00000000     0x1000 node/CMakeFiles/mosaic_node.dir/node_main.c.o
"""


class FwBudgetTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fw = Path(tmp.name) / "firmware"
        for rel in ("node/node_main.c", "audio/audio_dsp.c"):
            (self.fw / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.fw / rel).write_text("")
        self.build = self.fw / "build"

    def test_parse_keeps_placed_sections_only(self):
        placed = fw_budget.parse_map(MAP)
        names = [p.section for p in placed]
        # Discarded (address 0), debug and pre-map entries are skipped; wrapped lines are joined.
        self.assertEqual(names, [".text.main", ".text.cyw43_ll_bus_init", ".bss.memp_memory_PBUF_POOL_base",
                                 ".data.counter", ".bss", ".text.memcpy", ".heap"])
        self.assertEqual(placed[1].size, 0x2000)

    def test_source_file_only_resolves_our_code(self):
        sf = lambda obj: fw_budget.source_file(obj, self.build, self.fw)  # noqa: E731
        self.assertEqual(sf("node/CMakeFiles/mosaic_node.dir/node_main.c.o"), self.fw / "node/node_main.c")
        self.assertEqual(sf("audio/libaudio_dsp.a(audio_dsp.c.o)"), self.fw / "audio/audio_dsp.c")
        self.assertIsNone(sf("node/CMakeFiles/mosaic_node.dir/sdk/lib/lwip/src/core/memp.c.o"))
        self.assertIsNone(sf("/opt/arm/lib/libc_nano.a(lib_a-memcpy.o)"))

    def test_breakdown_by_component(self):
        old = fw_budget.FIRMWARE_DIR
        fw_budget.FIRMWARE_DIR = self.fw  # component() uses the default firmware dir
        try:
            b = fw_budget.breakdown(fw_budget.parse_map(MAP), self.build)
        finally:
            fw_budget.FIRMWARE_DIR = old
        self.assertEqual(b.flash["Our code"], 0x128 + 0x4)  # .data initial values live in flash too
        self.assertEqual(b.ram["Our code"], 0x4 + 0x7d00)
        self.assertEqual(b.flash["Wi-Fi driver (CYW43)"], 0x2000)
        self.assertEqual(b.ram["lwIP"], 0x8f90)
        self.assertEqual(b.flash["C library and compiler"], 0x40)
        self.assertEqual(sum(b.ram.values()), 0x4 + 0x7d00 + 0x8f90)  # .heap reservation excluded

    def test_float_helper_pattern(self):
        for name in ("__aeabi_fmul", "__aeabi_dadd", "__aeabi_i2f", "__aeabi_ul2f", "__aeabi_f2iz", "cosf", "powf", "sqrt"):
            self.assertRegex(name, fw_budget.FLOAT_HELPER)
        for name in ("__aeabi_idiv", "__aeabi_uidivmod", "__aeabi_lmul", "memcpy", "cosine_table"):
            self.assertNotRegex(name, fw_budget.FLOAT_HELPER)


if __name__ == "__main__":
    unittest.main()

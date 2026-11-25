# Firmware resource budget

> **Historical record (status at hand-in, 25 Nov 2026).** The measurements below are mostly of the earlier CMake/FreeRTOS builds. For the submitted µT-Kernel node, CI's resource-budget step reports flash and RAM on every run. For the system as submitted, start at the [main README](../README.md) and the [evidence index](README.md).

How much flash and RAM each firmware build uses, what fills it, and where our own code
still calls floating-point code. Part of the Week 13 evidence (see
`evidence_plan_week13.md`, section 2).

## How the numbers are made

`firmware/tools/fw_budget.py` reads the ELF and linker map of each build and writes a
Markdown report. It runs on every pull request in CI (the "Resource budget" step); the
report is on the run's summary page and in the `firmware-uf2` download. To run it locally
after a build:

```sh
python3 firmware/tools/fw_budget.py firmware/build --out budget.md
```

It covers `mosaic_node`, `mosaic_node_rtos` (when built), `audio_talking` (microphone,
fixed-point DSP and the int8 classifier) and `audio_benchmark`. Each report names the
firmware commit, compiler and Pico SDK it came from.

The node now runs micro T-Kernel 3.0 from the course template in `node/`, built with
`make`. The same tool reads that build: CI's "Build node" job builds the default, `NET=lwip`
and `TEST=1` images and attaches their report to the `node-uf2` download. Locally:

```sh
cd node/build_make && make -j8 && cd ../..
python3 firmware/tools/fw_budget.py node/build_make --out budget.md
```

In the template build, "our code" is `node/app_program/` only; the kernel, BSP, Wi-Fi,
lwIP and USB code is the template's.

## The micro T-Kernel node (`node/`), template as imported

Local build, Pico SDK 2.3.0 and Arm GCC 15.2, commit `af1c55d` (the template before any
MOSAIC code moves in; `app_program/` still holds the template's example subsystems):

| Image | Flash used (of 2 MB) | Static RAM (of 256 KB) | Rest of RAM: kernel memory pool and exception stack |
|---|---:|---:|---:|
| default (USB console, Wi-Fi) | 278.7 KB (13.6 %) | 24.0 KB (9.4 %) | 232.0 KB |
| `NET=lwip` (adds lwIP, which our UDP protocol needs) | 321.3 KB (15.7 %) | 80.2 KB (31.3 %) | 176.0 KB |
| `TEST=1` (self-tests) | 280.9 KB (13.7 %) | 24.0 KB (9.4 %) | 232.0 KB |

- **lwIP is the big RAM cost:** 56 KB static, mostly a 35.9 KB packet pool and a 16 KB
  heap set in the template's `lwipopts.h`. That's shared template code, so changing it
  needs the team and the instructor.
- **Task stacks come out of the kernel's memory pool,** not static RAM: about 176 KB is left
  for them in the `NET=lwip` image. Our audio buffers (about 62 KB in `audio_talking`) would
  sit in static RAM on top of the 80 KB.
- No float calls in the template's `app_program/` code. The check will cover our code once
  it moves into `node/app_program/`.

## Status on 16 Nov 2026

| Number | Status |
|---|---|
| Flash and static RAM, plain node and audio builds | Measured on a local build: `evidence/firmware-budget/local-sdk-2.3.0.md` |
| Same, from the team's build (SDK 1.5.1, GCC 10.3) and the RTOS node | CI produces it on the next pull request; copy it into `evidence/firmware-budget/` |
| Float calls in our code | Measured; see below |
| Node with audio linked in | Not possible yet: audio isn't in the node build |
| Stack high-water marks, minimum free kernel memory | To do on the micro T-Kernel node; the template doesn't report them yet (Arif) |
| CPU load per task | To do on the micro T-Kernel node (Arif) |
| DSP and inference time per window | Week 10 tests B2/B3 (Moe, Darius) |

The local numbers come from SDK 2.3.0 and GCC 15.2, not the team's SDK 1.5.1 and GCC
10.3, so they may differ by a few KB. Use the CI report in the final write-up.

## What the local build shows (commit `535f2e9`)

| Build | Flash used (of 2 MB) | Static RAM (of 256 KB) | Our code: flash / RAM |
|---|---:|---:|---:|
| `mosaic_node` (sensors + Wi-Fi, no audio) | 330.6 KB (16.1 %) | 57.7 KB (22.5 %) | 14.1 KB / 1.5 KB |
| `audio_talking` (mic + DSP + int8 classifier) | 36.7 KB (1.8 %) | 86.2 KB (33.7 %) | 9.2 KB / 80.0 KB |

- **Flash isn't a concern.** 240 KB of the node's 331 KB is the Wi-Fi chip's driver and
  firmware image. Our own node code is 14 KB.
- **RAM is where the audio integration will be tight.** The audio build's 80 KB is mostly
  two 31.2 KB sample buffers (`raw_audio` in `audio_capture.c`, `filtered_audio` in
  `audio_dsp.c`) and a 10 KB mel filter table. The team's CI build (SDK 1.5.1, PR #26) puts
  the RTOS node at 121.7 KB of static RAM, 64 KB of it the FreeRTOS heap that holds the
  task stacks. Adding the audio buffers gives roughly 200 KB of 256 KB, leaving about
  55 KB. That's an estimate from separate builds; the real figure comes from the RTOS
  build once audio is linked. If it runs short, the options are the lwIP packet pool
  (36 KB), sizing the FreeRTOS heap from the measured high-water marks, and moving the
  DSP tables to flash.
- **The node's biggest RAM user is lwIP's packet pool,** 35.9 KB (`PBUF_POOL_SIZE 24` in
  `lwipopts.h`). We only send small UDP datagrams, so this is the first place to free RAM
  if the audio build runs short. That's Arif's call; nothing was changed here.

## Floating-point check

The RP2040 has no FPU, so any float maths compiles to calls such as `__aeabi_fmul` or
`cosf`. The script lists every such call in our object files, by function.

| Where | Float calls | In the per-window path? |
|---|---|---|
| Node: `node_main.c`, `environment.c`, `sensors.c`, `dht22.c` | None | n/a |
| Classifier: `dsp_int8_candidate.c`, `classifier_probabilities.c`, `audio_talking.c` | None | n/a |
| `audio_dsp.c`: `audio_dsp_init` | `cosf`, `sinf`, `powf`, `floorf`, `lrintf` and float arithmetic | **No.** It builds the Hamming window, FFT twiddle, DCT and mel tables once at start-up and stores them as Q15 (DCT: Q14) integers. `audio_dsp_process`, which runs every window, has no float calls. |
| `audio_benchmark.c`: `main` | Float arithmetic and `__aeabi_f2d` | No. It turns timer counts into milliseconds for printing; it's a test program, not the node. |

So the processing path is integer-only in the build, not just in the source. The
start-up tables are the one place a reviewer could object to. Precomputing them as
`const` arrays would remove the last float code and move more than 11 KB of tables from
RAM to flash. That's Moe's decision; it isn't changed here.

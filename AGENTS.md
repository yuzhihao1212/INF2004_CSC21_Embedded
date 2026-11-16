# Rules for AI assistants in this repo

Codex reads this file directly; Claude Code reads it through `CLAUDE.md`. These are fixed
project constraints. Don't reopen them, and don't suggest dropping, deferring or replacing
them.

## μT-Kernel 3.0 is a hard requirement for the node

- The sensing-node firmware must run on **μT-Kernel 3.0**. This is a hard requirement of the
  project (confirmed by ZhiHao, 16 Nov 2026). Never propose FreeRTOS, bare metal or any other
  RTOS for the node, and never suggest demoing the node on FreeRTOS instead.
- The course provides a project template with the kernel already ported to the Pico W:
  `sirfonzie/INF2004_ProjectTemplate`, forked as `yuzhihao1212/INF2004_micro-t-kernel`. It runs
  μT-Kernel 3.0 on both RP2040 cores and includes the USB console, the CYW43 Wi-Fi driver,
  lwIP and MQTT. It builds with `make` in `build_make/` against Pico SDK 2.2.0 (2.3.0 also
  tested). Its README says the port is derived from TRON's `mtk3_bsp`, branch `pico_rp2040`.
- `firmware/utk/` on branch `feat/utkernel-port` is a separate single-core port we started
  before finding the template. Where the template's code sits in this repo, and whether
  `firmware/utk/` is kept, are still open (see `docs/decision-log.md`, 16 Nov). Don't extend
  either until ZhiHao decides.
- Before any node work, read the template's `README.md`, `TEAM.md` and `testing/README.md`.
  They set the instructor's rules, and they win if this summary ever differs:
  - one folder per student, `app_program/subsystemN/`, edited only by its owner; drivers live
    there as `drv_<name>.c`/`.h`, never under `device/`
  - claim pins and peripherals in `TEAM.md` before using them; each peripheral is driven by
    exactly one owning task, and other tasks ask that task through a kernel object
  - no application task calls `cyw43_*`, lwIP or MQTT functions; network code runs inside the
    kernel's `cyw43_utk_task`, and changing that shared code needs the team and the
    instructor to agree
  - every test goes in `testing/` with an ID, the commit tested, the result and a saved log;
    old results are never edited
- Any node work that depends on the RTOS (tasks, audio, watchdog supervision, CPU load,
  stack and heap reporting) targets μT-Kernel and its `tk_*` API. Don't add features to the
  FreeRTOS target (`mosaic_node_rtos`, `firmware/node/rtos/`).
- If a plan runs into a real limit of the template or the kernel, say so and propose a fix
  within μT-Kernel. Raising risks is fine; recommending another RTOS isn't.

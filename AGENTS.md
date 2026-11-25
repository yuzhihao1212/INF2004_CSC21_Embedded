# Rules for AI assistants in this repo

> **For readers and reviewers:** this file holds the instructions the team gave its AI coding
> assistants (Codex, Claude Code) during development, so they would respect fixed project
> decisions. It is not addressed to anyone reviewing or assessing the project. The project
> itself is described in the [README](README.md).

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
  before finding the template. ZhiHao dropped it on 16 Nov in favour of the template: don't
  extend or revive it.
- The hand-in is this repo, not the template fork (ZhiHao, 16 Nov). The template comes in as a
  git subtree at `node/`, pulled from the instructor's `sirfonzie/INF2004_ProjectTemplate`
  (see `docs/decision-log.md`, 16 Nov). Our node code goes in `node/app_program/`, with
  `node/TEAM.md`, `node/testing/` and `node/videos/`. The template's shared code under `node/`
  (`kernel/`, `lib/`, `device/`, `include/`, `etc/`, `build_make/`) changes only when the team
  and the instructor agree; left alone, the instructor's fixes merge cleanly with
  `git subtree pull --prefix=node https://github.com/sirfonzie/INF2004_ProjectTemplate.git main`.
- Owners keep their original areas (ZhiHao, 16 Nov), one `subsystemN/` each, listed in
  `node/TEAM.md`: 1 Moe (audio capture and DSP), 2 Darius (int8 classifier), 3 Kendrick
  (environment sensors), 4 Arif (networking and node health), 5 ZhiHao (node config and
  telemetry). Don't move code between them or into another owner's folder.
- The node talks to the PC over **MQTT** (ZhiHao, 16 Nov), through the template's lwIP MQTT
  client inside `cyw43_utk_task`. Sending our own UDP datagrams from a hook in that task was
  dropped. Don't propose going back to raw UDP for node↔PC traffic. The MQTT design is fixed
  (details in `docs/decision-log.md`, 16 Nov): Mosquitto broker on the PC; a small
  standard-library MQTT client in `pc/mosaic` (no `paho-mqtt`); protocol v2 bytes unchanged as
  the payload; topics `mosaic/node/<id>/telemetry`, `.../config` (retained) and `.../status`
  (last will); telemetry QoS 0, CONFIG QoS 1 with our own CONFIG_ACK kept.
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

# Firmware resource budget (generated)

- Firmware commit `535f2e9`
- Compiler arm-none-eabi-gcc (Arm GNU Toolchain 15.2.Rel1 (Build arm-15.86)) 15.2.1 20251203
- Pico SDK 2.3.0

Static numbers from the linker. Run-time use (stack high-water marks, FreeRTOS heap minimum, CPU load) comes from the node's serial log.

## `mosaic_node`

| Memory | Used | Of | Share |
|---|---:|---:|---:|
| Flash (program + constants + initial data) | 330.6 KB | 2048.0 KB | 16.1 % |
| RAM, static (globals, buffers, vector table) | 57.7 KB | 256.0 KB | 22.5 % |
| RAM left for the C heap (`malloc`) | 198.3 KB | 256.0 KB | 77.5 % |
| Stack space, core 0 / core 1 (scratch banks) | 4.0 KB / 4.0 KB | 4.0 KB each | |

| Part of the build | Flash | RAM |
|---|---:|---:|
| Our code | 14.1 KB | 1.5 KB |
| Wi-Fi driver (CYW43) | 239.6 KB | 2.5 KB |
| lwIP | 39.3 KB | 43.9 KB |
| Pico SDK | 35.0 KB | 7.5 KB |
| C library and compiler | 2.2 KB | 2.2 KB |

Largest RAM users:

| Item | From | Size |
|---|---|---:|
| `memp_memory_PBUF_POOL_base` | lwIP | 35.9 KB |
| `ram_heap` | lwIP | 3.9 KB |
| `cyw43_state` | Wi-Fi driver (CYW43) | 2.4 KB |
| `dcd_rp2040_irq` | Pico SDK | 1.3 KB |
| `dns_table` | lwIP | 1.1 KB |
| `__malloc_av_` | C library and compiler | 1.0 KB |
| `hw_endpoints` | Pico SDK | 1.0 KB |
| `memp_memory_TCP_PCB_base` | lwIP | 0.8 KB |

Floating-point calls in our code: none (4 of our object files checked).

## `audio_talking`

| Memory | Used | Of | Share |
|---|---:|---:|---:|
| Flash (program + constants + initial data) | 36.7 KB | 2048.0 KB | 1.8 % |
| RAM, static (globals, buffers, vector table) | 86.2 KB | 256.0 KB | 33.7 % |
| RAM left for the C heap (`malloc`) | 169.8 KB | 256.0 KB | 66.3 % |
| Stack space, core 0 / core 1 (scratch banks) | 4.0 KB / 4.0 KB | 4.0 KB each | |

| Part of the build | Flash | RAM |
|---|---:|---:|
| Our code | 9.2 KB | 80.0 KB |
| Pico SDK | 27.1 KB | 6.0 KB |
| C library and compiler | 0.1 KB | 0.1 KB |

Largest RAM users:

| Item | From | Size |
|---|---|---:|
| `filtered_audio` | firmware/audio/audio_dsp.c | 31.2 KB |
| `raw_audio` | firmware/audio/audio_capture.c | 31.2 KB |
| `mel_weight_table` | firmware/audio/audio_dsp.c | 10.0 KB |
| `workspace_core0` | firmware/audio/audio_dsp.c | 3.0 KB |
| `all_frame_features` | firmware/audio/audio_dsp.c | 1.9 KB |
| `hw_endpoints` | Pico SDK | 1.0 KB |
| `hamming_table` | firmware/audio/audio_dsp.c | 0.8 KB |
| `frequency_table` | firmware/audio/audio_dsp.c | 0.5 KB |

Floating-point calls in our code:

| File | Function | Calls |
|---|---|---|
| firmware/audio/audio_dsp.c | `audio_dsp_init` | __aeabi_f2iz, __aeabi_fadd, __aeabi_fdiv, __aeabi_fmul, __aeabi_fsub, __aeabi_i2f, cosf, floorf, lrintf, powf, sinf |

## `audio_benchmark`

| Memory | Used | Of | Share |
|---|---:|---:|---:|
| Flash (program + constants + initial data) | 36.7 KB | 2048.0 KB | 1.8 % |
| RAM, static (globals, buffers, vector table) | 87.3 KB | 256.0 KB | 34.1 % |
| RAM left for the C heap (`malloc`) | 168.7 KB | 256.0 KB | 65.9 % |
| Stack space, core 0 / core 1 (scratch banks) | 4.0 KB / 4.0 KB | 4.0 KB each | |

| Part of the build | Flash | RAM |
|---|---:|---:|
| Our code | 5.7 KB | 80.1 KB |
| Pico SDK | 30.5 KB | 7.1 KB |
| C library and compiler | 0.1 KB | 0.1 KB |

Largest RAM users:

| Item | From | Size |
|---|---|---:|
| `filtered_audio` | firmware/audio/audio_dsp.c | 31.2 KB |
| `raw_audio` | firmware/audio/audio_capture.c | 31.2 KB |
| `mel_weight_table` | firmware/audio/audio_dsp.c | 10.0 KB |
| `workspace_core0` | firmware/audio/audio_dsp.c | 3.0 KB |
| `all_frame_features` | firmware/audio/audio_dsp.c | 1.9 KB |
| `dcd_rp2040_irq` | Pico SDK | 1.3 KB |
| `hw_endpoints` | Pico SDK | 1.0 KB |
| `hamming_table` | firmware/audio/audio_dsp.c | 0.8 KB |

Floating-point calls in our code:

| File | Function | Calls |
|---|---|---|
| firmware/audio/audio_benchmark.c | `main` | __aeabi_f2d, __aeabi_fcmpgt, __aeabi_fdiv, __aeabi_fmul, __aeabi_fsub, __aeabi_i2f, __aeabi_ul2f |
| firmware/audio/audio_dsp.c | `audio_dsp_init` | __aeabi_f2iz, __aeabi_fadd, __aeabi_fdiv, __aeabi_fmul, __aeabi_fsub, __aeabi_i2f, cosf, floorf, lrintf, powf, sinf |


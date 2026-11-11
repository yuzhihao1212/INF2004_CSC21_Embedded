#ifndef MOSAIC_FREERTOS_CONFIG_H
#define MOSAIC_FREERTOS_CONFIG_H

#include <stdint.h>
#include <stddef.h>

#define configUSE_PREEMPTION 1
#define configUSE_TIME_SLICING 1
#define configUSE_TICKLESS_IDLE 0
#define configTICK_RATE_HZ 1000
#define configMAX_PRIORITIES 5
#define configMINIMAL_STACK_SIZE 512
#define configMAX_TASK_NAME_LEN 16
#define configUSE_16_BIT_TICKS 0
#define configIDLE_SHOULD_YIELD 1
#define configUSE_MUTEXES 1
#define configUSE_RECURSIVE_MUTEXES 1
#define configUSE_COUNTING_SEMAPHORES 1
#define configUSE_TIMERS 1
#define configTIMER_TASK_PRIORITY 4
#define configTIMER_QUEUE_LENGTH 10
#define configTIMER_TASK_STACK_DEPTH 512
#define configUSE_IDLE_HOOK 0
#define configUSE_PASSIVE_IDLE_HOOK 0
#define configUSE_TICK_HOOK 0
#define configUSE_NEWLIB_REENTRANT 0
#define configSUPPORT_STATIC_ALLOCATION 0
#define configSUPPORT_DYNAMIC_ALLOCATION 1
#define configTOTAL_HEAP_SIZE (64 * 1024)
#define configCHECK_FOR_STACK_OVERFLOW 2
#define configUSE_MALLOC_FAILED_HOOK 1
#define configSTACK_DEPTH_TYPE uint32_t
#define configMESSAGE_BUFFER_LENGTH_TYPE size_t
#define configNUM_THREAD_LOCAL_STORAGE_POINTERS 5
#define configENABLE_BACKWARD_COMPATIBILITY 1
/* Default is one core; the optional team audio task requires two. */
#define configNUMBER_OF_CORES MOSAIC_RTOS_CORES
#define configNUM_CORES MOSAIC_RTOS_CORES
#if MOSAIC_RTOS_CORES > 1
#define configUSE_CORE_AFFINITY 1
#endif
#define configTICK_CORE 0
#define configRUN_MULTIPLE_PRIORITIES 1
#define configSUPPORT_PICO_SYNC_INTEROP 1
#define configSUPPORT_PICO_TIME_INTEROP 1
#define INCLUDE_vTaskDelay 1
#define INCLUDE_vTaskDelayUntil 1
#define INCLUDE_vTaskSuspend 1
#define INCLUDE_xTaskGetSchedulerState 1
#define INCLUDE_xTaskGetCurrentTaskHandle 1
#define INCLUDE_uxTaskGetStackHighWaterMark 1
#define INCLUDE_xTimerPendFunctionCall 1

void mosaic_rtos_panic(void);
#define configASSERT(x) do { if (!(x)) mosaic_rtos_panic(); } while (0)
#endif

#ifndef S3_STARTUP_MOCK_H
#define S3_STARTUP_MOCK_H
#define APP_H
#include <stdint.h>
typedef int32_t ER, ID, BOOL, INT, W, PRI;
typedef uint32_t UW;
typedef void (*FP)(INT, void *);
typedef struct { unsigned mbxatr; } T_CMBX;
typedef struct { unsigned mtxatr; } T_CMTX;
typedef struct { FP task; unsigned tskatr; PRI itskpri; int stksz; UW assprc; } T_CTSK;
typedef struct { unsigned tskstat; } T_RTSK;
#define IMPORT extern
#define EXPORT
#define LOCAL static
#define E_OK 0
#define E_OBJ (-41)
#define TA_TFIFO 1u
#define TA_MFIFO 2u
#define TA_INHERIT 4u
#define TA_HLNG 8u
#define TA_RNG3 16u
#define TA_ASSPRC 32u
#define TP_PRC1 1u
#define TK_SUPPORT_SMP 1
#define TASK_STACK_SIZE 2048
#define TTS_DMT 16u
ID tk_cre_mbx(const T_CMBX *);
ID tk_cre_mtx(const T_CMTX *);
ER tk_del_mbx(ID);
ID tk_cre_tsk(const T_CTSK *);
ER tk_sta_tsk(ID, INT);
ER tk_ref_tsk(ID, T_RTSK *);
ER subsystem3_init(void);
ER subsystem3_start(void);
#endif

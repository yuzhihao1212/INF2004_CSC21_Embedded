#ifndef S3_UTK_MOCK_H
#define S3_UTK_MOCK_H
/* Skip app.h only for host tests. S5's real header still checks signatures. */
#define APP_H
#include <stdint.h>
typedef int32_t ER;
typedef int32_t ID;
typedef int32_t BOOL;
typedef int32_t INT, W;
typedef uint32_t UW;
typedef struct { uint32_t lo; int32_t hi; } SYSTIM;
#define IMPORT extern
#define E_OK 0
#define E_TMOUT (-50)
#define E_OBJ (-41)
#define CHECK(er, what) do { (void)(er); (void)(what); } while (0)
ER tk_get_otm(SYSTIM *);
ER tk_dly_tsk(unsigned);
void tk_ext_tsk(void);
#endif

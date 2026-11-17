#include "startup_mock.h"
#include "subsystem3.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static int fail_create_pri, fail_start_pri, creations[2], starts[2];
static unsigned states[2];
static int idx(ID id) { assert(id == 10 || id == 11); return (int)id - 10; }
void consumer_task(INT s, void *p) { (void)s; (void)p; }
void environment_task(INT s, void *p) { (void)s; (void)p; }
ID tk_cre_mbx(const T_CMBX *p) { (void)p; return 1; }
ID tk_cre_mtx(const T_CMTX *p) { (void)p; return 2; }
ER tk_del_mbx(ID id) { (void)id; return E_OK; }
ID tk_cre_tsk(const T_CTSK *p)
{
    int i = p->itskpri == S3_PRI_CONSUMER ? 0 : 1;
    assert(p->itskpri == (i ? S3_PRI_ENVIRONMENT : S3_PRI_CONSUMER));
    assert(p->stksz == 2048 && p->assprc == TP_PRC1);
    if (fail_create_pri == p->itskpri) { fail_create_pri = 0; return -12; }
    ++creations[i]; states[i] = TTS_DMT; return 10 + i;
}
ER tk_sta_tsk(ID id, INT code)
{
    int i = idx(id); (void)code;
    assert(states[i] == TTS_DMT);
    if (fail_start_pri == (i ? S3_PRI_ENVIRONMENT : S3_PRI_CONSUMER)) {
        fail_start_pri = 0; return -13;
    }
    ++starts[i]; states[i] = 1; return E_OK;
}
ER tk_ref_tsk(ID id, T_RTSK *out) { out->tskstat = states[idx(id)]; return E_OK; }

int main(int argc, char **argv)
{
    assert(argc == 2 && subsystem3_init() == E_OK);
    if (!strcmp(argv[1], "consumer-create")) fail_create_pri = S3_PRI_CONSUMER;
    else if (!strcmp(argv[1], "consumer-start")) fail_start_pri = S3_PRI_CONSUMER;
    else if (!strcmp(argv[1], "environment-create")) fail_create_pri = S3_PRI_ENVIRONMENT;
    else if (!strcmp(argv[1], "environment-start")) fail_start_pri = S3_PRI_ENVIRONMENT;
    else assert(!strcmp(argv[1], "success"));
    if (strcmp(argv[1], "success")) {
        assert(subsystem3_start() < 0);
        assert(tid_environment == 0);
    }
    assert(subsystem3_start() == E_OK);
    assert(tid_environment == 11);
    assert(subsystem3_start() == E_OK);
    assert(creations[0] == 1 && creations[1] == 1);
    assert(starts[0] == 1 && starts[1] == 1);
    states[1] = TTS_DMT; /* unexpected environment task exit */
    assert(subsystem3_start() == E_OBJ);
    assert(starts[0] == 1 && starts[1] == 1);
    printf("PASS S3-U19: startup retry/idempotence/exit (%s, simulated)\n", argv[1]);
    return 0;
}

#include "s4_health.h"

static ID progress;

ER s4_health_init(void)
{
    T_CFLG flag = {0};
    flag.flgatr = TA_TFIFO;
    progress = tk_cre_flg(&flag);
    return progress < E_OK ? progress : E_OK;
}

ER s4_health_mark(UINT bits)
{
    if (!bits || (bits & ~S4_HEALTH_ALL)) return E_PAR;
    if (progress <= 0) return E_OBJ;
    return tk_set_flg(progress, bits);
}

ER s4_health_take(UINT required)
{
    UINT seen;
    if (!required || (required & ~S4_HEALTH_ALL)) return E_PAR;
    if (progress <= 0) return E_OBJ;
    return tk_wai_flg(progress, required, TWF_ANDW | TWF_BITCLR, &seen, TMO_POL);
}

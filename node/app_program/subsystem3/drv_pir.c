#include "drv_pir.h"
#include <sys/sysdepend/cpu/rp2040/sysdef.h>

#define S3_PIR_PIN 16u

ER s3_pir_init(void)
{
    ER er = gpio_set_pin(S3_PIR_PIN, GPIO_MODE_IN);
    if (er != E_OK) return er;
    /* Explicit pull-down matches the prior Pico SDK driver. This does not
     * detect an unplugged sensor; an open input will normally read low. */
    clr_w(GPIO(S3_PIR_PIN), GPIO_PUE);
    set_w(GPIO(S3_PIR_PIN), GPIO_PDE);
    return E_OK;
}

BOOL s3_pir_read(void)
{
    return gpio_get_val(S3_PIR_PIN) != 0;
}

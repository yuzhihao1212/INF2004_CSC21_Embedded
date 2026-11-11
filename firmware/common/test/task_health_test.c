#include <assert.h>
#include "task_health.h"

int main(void) {
    mosaic_task_health_t h = {0};
    assert(!mosaic_task_health_take(&h)); /* Startup cannot feed early. */
    for (unsigned i = 0; i < 100; ++i) {
        mosaic_task_health_mark(&h, MOSAIC_HEALTH_NETWORK);
        assert(!mosaic_task_health_take(&h)); /* Busy peer cannot hide a hang. */
    }
    mosaic_task_health_mark(&h, MOSAIC_HEALTH_ENVIRONMENT);
#ifdef MOSAIC_NODE_AUDIO_ENABLED
    assert(!mosaic_task_health_take(&h));
    mosaic_task_health_mark(&h, MOSAIC_HEALTH_AUDIO);
#endif
    assert(mosaic_task_health_take(&h));
    assert(!mosaic_task_health_take(&h)); /* Previous epoch is consumed. */
    for (unsigned i = 0; i < 100; ++i) {
        mosaic_task_health_mark(&h, MOSAIC_HEALTH_ENVIRONMENT);
        assert(!mosaic_task_health_take(&h));
    }
    mosaic_task_health_mark(&h, 0x80u);
    assert(!mosaic_task_health_take(&h)); /* Unknown bits are not progress. */
    mosaic_task_health_mark(&h, MOSAIC_HEALTH_NETWORK);
#ifdef MOSAIC_NODE_AUDIO_ENABLED
    assert(!mosaic_task_health_take(&h));
    mosaic_task_health_mark(&h, MOSAIC_HEALTH_AUDIO);
#endif
    assert(mosaic_task_health_take(&h));
    /* No link/sensor-validity dependency: both live loops permit feeding even
     * during a reconnect or sensor error, as long as they continue iterating. */
    for (unsigned i = 0; i < 120; ++i) {
        mosaic_task_health_mark(&h, MOSAIC_HEALTH_REQUIRED);
        assert(mosaic_task_health_take(&h));
    }
    return 0;
}

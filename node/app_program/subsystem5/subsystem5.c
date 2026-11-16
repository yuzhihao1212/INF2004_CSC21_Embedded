#include "s5_internal.h"

ID mtx_s5;
ID mbf_s5_rx;
ID mbf_s5_tx;
s5_state_t s5_state;

uint64_t s5_now_ms(void)
{
    SYSTIM time = {0};
    tk_get_tim(&time);
    return ((uint64_t)(uint32_t)time.hi << 32) | time.lo;
}

static ER lock_state(void)
{
    if (mtx_s5 <= 0) return E_OBJ;
    return tk_loc_mtx(mtx_s5, S5_LOCK_TMO_MS);
}

ER subsystem5_init(void)
{
    T_CMTX m = {0};
    T_CMBF b = {0};
    s5_init(&s5_state, MOSAIC_NODE_ID);
    m.mtxatr = TA_INHERIT;
    ID id = tk_cre_mtx(&m);
    if (id <= 0) return id;
    mtx_s5 = id;
    b.mbfatr = TA_TFIFO;
    b.bufsz = S5_RX_BUFSZ;
    b.maxmsz = S5_RX_MAX;
    id = tk_cre_mbf(&b);
    if (id <= 0) goto fail_mutex;
    mbf_s5_rx = id;
    b.bufsz = S5_TX_BUFSZ;
    b.maxmsz = S5_TX_MAX;
    id = tk_cre_mbf(&b);
    if (id <= 0) goto fail_rx;
    mbf_s5_tx = id;
    return E_OK;
fail_rx:
    tk_del_mbf(mbf_s5_rx);
    mbf_s5_rx = 0;
fail_mutex:
    tk_del_mtx(mtx_s5);
    mtx_s5 = 0;
    return id;
}

ER subsystem5_start(void)
{
    if (mtx_s5 <= 0 || mbf_s5_rx <= 0 || mbf_s5_tx <= 0) return E_OBJ;
    tm_printf((UB*)"MOSAIC node %u: subsystem 5 config and telemetry\n",
              (unsigned)MOSAIC_NODE_ID);
    ID tid = app_start_task((FP)report_task, S5_PRI_REPORT, 0, "report_task");
    return tid < E_OK ? tid : E_OK;
}

ER s5_get_config(mosaic_config_t *out)
{
    if (!out) return E_PAR;
    ER er = lock_state();
    if (er != E_OK) return er;
    *out = s5_state.config;
    return tk_unl_mtx(mtx_s5);
}

ER s5_post_environment(int16_t temperature_x10, uint16_t humidity_x10,
                         uint16_t co2_ppm, uint8_t valid_bits)
{
    ER er = lock_state();
    if (er != E_OK) return er;
    s5_update_environment(&s5_state, temperature_x10, humidity_x10, co2_ppm,
                          valid_bits, s5_now_ms());
    return tk_unl_mtx(mtx_s5);
}

ER s5_post_pir(uint32_t samples, uint32_t active)
{
    ER er = lock_state();
    if (er != E_OK) return er;
    s5_update_pir(&s5_state, samples, active);
    return tk_unl_mtx(mtx_s5);
}

ER s5_post_audio_window(const mosaic_audio_window_t *window,
                         uint32_t dsp_us, uint32_t inference_us)
{
    ER er = lock_state();
    if (er != E_OK) return er;
    bool ok = s5_publish_audio(&s5_state, window, dsp_us, inference_us);
    er = tk_unl_mtx(mtx_s5);
    return er != E_OK ? er : (ok ? E_OK : E_PAR);
}

ER s5_audio_dropped(uint16_t windows)
{
    ER er = lock_state();
    if (er != E_OK) return er;
    s5_capture_dropped(&s5_state, windows);
    return tk_unl_mtx(mtx_s5);
}

ER s5_post_health(int8_t rssi_dbm, uint8_t cpu_load_pct, uint32_t free_heap_bytes)
{
    ER er = lock_state();
    if (er != E_OK) return er;
    s5_update_health(&s5_state, rssi_dbm, cpu_load_pct, free_heap_bytes);
    return tk_unl_mtx(mtx_s5);
}

#include "../subsystem5/subsystem5.h"
#include "../subsystem2/subsystem2.h"
#include "subsystem1.h"
#include "drv_audio.h"
#include "audio_dsp.h"
#include "audio_signal_quality.h"

void audio_task(INT stacd,void *exinf)
{
    (void)stacd; (void)exinf;
    audio_features_t msg={0};
    mosaic_config_t config=MOSAIC_DEFAULT_CONFIG;
    audio_dsp_init();
    ER er=audio_capture_start();
    if (er<0) {
        tm_printf((UB*)"audio init failed: %d\n",er);
        tk_exd_tsk(); return;
    }
    tm_printf((UB*)"audio: GP26 16kHz 500ms integer DSP\n");
    for (;;) {
        uint16_t *adc; audio_signal_quality_t q;
        ++msg.sequence;
        er=audio_capture_wait(&adc,&msg.captured_us);
        if (er<0) { tm_printf((UB*)"audio wait failed: %d\n",er); continue; }
        msg.capture_us=audio_capture_duration_us();
        mosaic_config_t updated;
        if (s5_get_config(&updated)==E_OK) config=updated;
        if (config.audio_gain_x256!=256) {
            uint32_t sum=0;
            for (unsigned i=0;i<8000;++i) sum+=adc[i];
            int32_t mean=(int32_t)(sum/8000);
            for (unsigned i=0;i<8000;++i) {
                int32_t v=mean+((int32_t)adc[i]-mean)*config.audio_gain_x256/256;
                adc[i]=(uint16_t)(v<0?0:v>4095?4095:v);
            }
        }
        if (!audio_signal_quality(adc,8000,&q)) continue;
        uint64_t start=audio_clock_us();
        audio_dsp_process(adc,msg.features);
        uint64_t end=audio_clock_us();
        msg.dsp_us=(uint32_t)(end-start);
        msg.rms_q8=q.ac_rms_q8; msg.clipped=q.clipped_samples;
        msg.adc_mean_q8=q.mean_q8; msg.adc_min=q.minimum; msg.adc_max=q.maximum;
        msg.timing_fault=end-msg.captured_us>500000;
        msg.threshold_pct=config.audio_conf_threshold_pct;
        /* Full queue drops the new observation. S2 sees the sequence gap
         * and accounts for drops in order, avoiding races with old results. */
        (void)tk_snd_mbf(mbf_audio_features,&msg,sizeof msg,TMO_POL);
    }
}

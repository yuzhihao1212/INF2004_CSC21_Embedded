#include "environment_service.h"
#include "utk_mock.h"
#include "subsystem5.h"
#include "s3_time.h"
#include "subsystem3.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static mosaic_config_t cfg;
static ER cfg_error, env_error, pir_error;
static uint32_t posted_samples, posted_active, env_calls, starts;
static int input[64], read_pos, read_count;
static bool uart_ready, tx_ready, hw_ready, dma_stopped, pir_high;
static int capture_result;
static uint8_t posted_flags;
static int16_t posted_temp;
static uint16_t posted_ppm;
ID tid_environment;
static uint32_t fake_time, delay_calls, task_exits, hw_stops;
ER tk_get_otm(SYSTIM *t) { t->lo = fake_time; fake_time += 1000; return E_OK; }
ER tk_dly_tsk(unsigned ms) { (void)ms; return ++delay_calls == 3 ? E_OBJ : E_OK; }
void tk_ext_tsk(void) { ++task_exits; }

ER s5_get_config(mosaic_config_t *out) { *out = cfg; return cfg_error; }
ER s5_post_environment(int16_t t, uint16_t h, uint16_t ppm, uint8_t flags)
{
    (void)h; ++env_calls; posted_temp=t; posted_ppm=ppm; posted_flags=flags;
    return env_error;
}
ER s5_post_pir(uint32_t samples, uint32_t active)
{
    if (!pir_error) { posted_samples+=samples; posted_active+=active; }
    return pir_error;
}
ER s3_pir_init(void) { return E_OK; }
BOOL s3_pir_read(void) { return pir_high; }
bool s3_uart1_init(void) { return uart_ready; }
int s3_uart1_read(void) { return read_pos < read_count ? input[read_pos++] : -1; }
bool s3_uart1_send(const uint8_t command[5])
{
    const uint8_t expected[] = {0xfe,0xa6,0,1,0xa7};
    assert(!memcmp(command, expected, 5));
    return tx_ready;
}
bool s3_dht_hw_init(s3_dht_t *d) { (void)d; return hw_ready; }
void s3_dht_hw_start(s3_dht_t *d) { (void)d; ++starts; }
int s3_dht_hw_result(s3_dht_t *d) { (void)d; return capture_result; }
void s3_dht_hw_stop(s3_dht_t *d) { (void)d; ++hw_stops; }
bool s3_dht_hw_stopped(s3_dht_t *d) { (void)d; return dma_stopped; }

static void reset(void)
{
    const mosaic_config_t defaults=MOSAIC_DEFAULT_CONFIG;
    cfg=defaults; cfg.config_version=1;
    cfg_error=env_error=pir_error=0;
    posted_samples=posted_active=env_calls=starts=0;
    read_pos=read_count=0;
    uart_ready=tx_ready=hw_ready=dma_stopped=pir_high=true;
    capture_result=0;
}
static void step(s3_service_t *s,uint32_t now)
{
    s3_service_step(s,now,true);
    s3_service_start_due(s,now);
}
static void pulses(s3_dht_t *d)
{
    uint8_t b[5]={2,160,128,34,0}; /* 67.2 %RH, -3.4 C */
    b[4]=(uint8_t)(b[0]+b[1]+b[2]+b[3]);
    d->pulses[0]=d->pulses[1]=78;
    for(unsigned i=0;i<40;++i) {
        d->pulses[2+2*i]=48;
        d->pulses[3+2*i]=(b[i/8] & (1u << (7-i%8))) ? 68 : 25;
    }
}
static void scheduling(uint32_t boot)
{
    reset(); s3_service_t s; s3_service_init(&s,boot);
    for(unsigned i=0;i<=1990;i+=10) step(&s,boot+i);
    assert(starts==0 && posted_samples==20 && posted_active==20);
    step(&s,boot+2000); assert(starts==1 && s.dht.active);
    pulses(&s.dht); capture_result=1;
    step(&s,boot+2010);
    assert(s.record.temperature_x10==-34 && s.record.dht_sample_ms==boot+2000);
    step(&s,boot+2100); assert(posted_temp==-34 && (posted_flags & MOSAIC_VALID_TEMP_HUM));
    cfg.dht_interval_ms=2000; cfg.co2_interval_ms=60000; ++cfg.config_version;
    step(&s,boot+2250);
    step(&s,boot+3999); assert(starts==1);
    step(&s,boot+4000); assert(starts==2);
    capture_result=0;
    step(&s,boot+4010); assert(s.record.dht_status==SENSOR_TIMEOUT && !s.dht.active);
    assert(!(s.record.validity_flags & ENV_DHT_VALID));
    uint32_t p=posted_samples; step(&s,boot+4100); assert(posted_samples>p);
    cfg.dht_interval_ms=1; ++cfg.config_version;
    step(&s,boot+4250); assert(s.bad_configs==1 && s.config.dht_interval_ms==2000);
    cfg_error=E_TMOUT;
    step(&s,boot+4500); assert(s.s5_errors>0 && s.config.dht_interval_ms==2000);
    assert(!s3_elapsed(boot+1,boot+2,1));
}
static void posting_and_isolation(void)
{
    reset(); hw_ready=false; s3_service_t s; s3_service_init(&s,0);
    pir_error=E_TMOUT; env_error=E_OBJ;
    step(&s,0); step(&s,100);
    assert(s.record.dht_status==SENSOR_RESOURCE_ERROR && s.pir_samples==2);
    assert(s.environment_result==E_OBJ && s.pir_result==E_TMOUT);
    pir_error=env_error=0; step(&s,200);
    assert(posted_samples==3 && posted_active==3 && s.pir_samples==0);
    pir_error=-5; step(&s,300); assert(!s.pir_samples && s.pir_dropped==1);
    pir_error=E_TMOUT;
    for(unsigned now=400;now<=2400;now+=100) step(&s,now);
    assert(!s.pir_samples && s.pir_dropped==2);
    /* Long interval remains honest: expiry is not renewed by posting. */
    environment_apply_co2(&s.record,SENSOR_OK,850,2500);
    s.co2.protocol.warmed=true;
    step(&s,7600);
    assert(!(posted_flags & MOSAIC_VALID_CO2));
}
static void uart_transport(void)
{
    reset(); s3_co2_driver_t d; environment_record_t r={0}; s3_co2_init(&d,0);
    s3_co2_service(&d,&r,119999); assert(r.co2_status==SENSOR_WARMING_UP);
    s3_co2_service(&d,&r,120000); assert(d.protocol.waiting);
    int good[]={0xfe,0xa6,4,1,3,0x52,0,0,0};
    for(unsigned i=1;i<8;++i) good[8]=(good[8]+good[i])&255;
    memcpy(input,good,sizeof good); read_count=4;
    s3_co2_service(&d,&r,120100); assert(d.protocol.waiting);
    read_count=9; s3_co2_service(&d,&r,120200);
    assert(r.co2_ppm==850 && (r.validity_flags & ENV_CO2_VALID));
    s3_co2_service(&d,&r,122000); assert(d.protocol.waiting);
    input[0]=-2; read_pos=0; read_count=1;
    s3_co2_service(&d,&r,122100); assert(r.co2_status==SENSOR_PROTOCOL_ERROR);
    s3_co2_service(&d,&r,124000); s3_co2_service(&d,&r,125000);
    assert(r.co2_status==SENSOR_TIMEOUT);
    tx_ready=false; s3_co2_service(&d,&r,126000);
    assert(!d.protocol.waiting && r.co2_status==SENSOR_PROTOCOL_ERROR);
    tx_ready=true; read_pos=0; read_count=64;
    s3_co2_service(&d,&r,128000); assert(read_pos==32 && !d.protocol.waiting);
    /* Warm-up cannot reappear after half a 32-bit wrap. */
    s3_acd1100_tick(&d.protocol,&r,UINT32_C(0x80020000));
    assert(r.co2_status!=SENSOR_WARMING_UP);
    (void)posted_ppm;
}
static void dht_recovery(void)
{
    reset(); s3_dht_t d; environment_record_t r={0};
    assert(s3_dht_init(&d) && s3_dht_start(&d,UINT32_MAX-5));
    dma_stopped=false; s3_dht_service(&d,&r,5);
    assert(d.stopping && d.active && !s3_dht_start(&d,6));
    capture_result=1; /* A late completion must not turn a timed-out read valid. */
    s3_dht_service(&d,&r,6);
    assert(d.active && !(r.validity_flags & ENV_DHT_VALID));
    dma_stopped=true; s3_dht_service(&d,&r,10);
    assert(!d.active && r.dht_status==SENSOR_TIMEOUT);
    assert(s3_dht_start(&d,2000)); pulses(&d); capture_result=1;
    d.pulses[81]=d.pulses[81]==25 ? 68 : 25; /* corrupt checksum bit */
    s3_dht_service(&d,&r,2010); assert(r.dht_status==SENSOR_CHECKSUM_ERROR);
    assert(s3_dht_start(&d,4000)); pulses(&d);
    s3_dht_service(&d,&r,4010); assert(r.dht_status==SENSOR_OK);
    assert(s3_dht_start(&d,6000)); capture_result=-1;
    s3_dht_service(&d,&r,6010); assert(r.dht_status==SENSOR_RESOURCE_ERROR);
}
static void stuck_dma_isolation(void)
{
    reset(); s3_service_t s; s3_service_init(&s,0);
    step(&s,0); step(&s,2000);
    assert(s.dht.active && starts==1);
    dma_stopped=false;
    step(&s,2010);
    assert(s.dht.active && s.dht.stopping);
    s.co2.protocol.warmed=true;
    uint32_t before=posted_samples;
    for (unsigned now=2100; now<=5000; now+=100) step(&s,now);
    assert(posted_samples>before && starts==1 && s.dht.active);
    assert(s.co2.protocol.attempted);
    dma_stopped=true; step(&s,5010);
    assert(!s.dht.stopping && s.record.dht_status==SENSOR_TIMEOUT);
    puts("PASS S3-U22: stuck DMA keeps buffer isolated while other service continues (simulated)");
}
static void task_progress_and_exit(void)
{
    reset(); fake_time=delay_calls=task_exits=hw_stops=0;
    tid_environment=42;
    uart_ready=false; /* sensor error must not stop task progress */
    uint32_t before=s3_environment_progress();
    environment_task(0, NULL);
    assert(s3_environment_progress()-before == 3);
    assert(task_exits==1 && tid_environment==0 && posted_samples>0 && hw_stops==1);
    puts("PASS S3-U20: real task loop progresses through sensor error and stops active capture on exit (simulated)");
}
int main(void)
{
    scheduling(0); scheduling(UINT32_MAX-2050);
    posting_and_isolation(); uart_transport(); dht_recovery(); stuck_dma_isolation();
    task_progress_and_exit();
    char tiny[1]={42}; environment_format_x10(tiny,1,INT16_MIN); assert(!tiny[0]);
    environment_format_x10(NULL,0,INT16_MIN);
    puts("PASS S3-U06..U09: scheduling/config/S5 errors, UART transport, DHT recovery, rollover and bounded formatting");
    return 0;
}

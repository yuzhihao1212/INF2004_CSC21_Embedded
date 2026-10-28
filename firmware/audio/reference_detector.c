#include "reference_detector.h"
#include <math.h>
#include <string.h>

void reference_detector_init(reference_detector_t *state) {
    memset(state,0,sizeof(*state));
    state->config=(reference_config_t){.25f,4.0f,250000,1500000};
}

static int valid(const reference_reading_t *r, uint64_t now, uint64_t max_age) {
    return r && r->valid==REFERENCE_INPUT_VALID && isfinite(r->rms) &&
        r->rms>=0 && r->rms<=4095 && r->speech_votes<=3 &&
        r->time_us<=now && now-r->time_us<=max_age;
}

static int fit(reference_detector_t *s) {
    unsigned n=s->count;
    float mx=0,my=0,var=0,cov=0,xx=0,xy=0;
    for (unsigned i=0;i<n;++i) { mx+=s->reference_power[i];my+=s->student_power[i]; }
    mx/=n;my/=n;
    for (unsigned i=0;i<n;++i) {
        float x=s->reference_power[i],y=s->student_power[i];
        var+=(x-mx)*(x-mx);cov+=(x-mx)*(y-my);xx+=x*x;xy+=x*y;
    }
    /* A constant reference cannot identify transfer gain and noise separately. */
    if (var<=1e-6f*mx*mx*n) return 0;
    s->power_scale=fmaxf(0,cov/var);
    s->noise_intercept=my-s->power_scale*mx;
    if (s->noise_intercept<0) {
        s->noise_intercept=0;
        s->power_scale=xx>0 ? fmaxf(0,xy/xx) : 0;
    }
    float residual[REFERENCE_CALIBRATION_MAX];
    for (unsigned i=0;i<n;++i) {
        residual[i]=fmaxf(0,s->student_power[i]-(s->power_scale*s->reference_power[i]+s->noise_intercept));
        for (unsigned j=i;j>0 && residual[j]<residual[j-1];--j) {
            float tmp=residual[j];residual[j]=residual[j-1];residual[j-1]=tmp;
        }
    }
    s->residual_upper=residual[(95*n+99)/100-1];
    s->ready=1;
    return 1;
}

reference_result_t reference_detector_update(reference_detector_t *s,
    const reference_reading_t *ref,const reference_reading_t *student,uint64_t now) {
    reference_result_t out={REF_UNKNOWN,"INVALID_OR_STALE_INPUT",0,0,s->count,0};
    if (!valid(ref,now,s->config.max_age_us)||!valid(student,now,s->config.max_age_us)) {
        s->speech=(talking_detector_state_t){0};return out;
    }
    uint64_t skew=ref->time_us>student->time_us ? ref->time_us-student->time_us : student->time_us-ref->time_us;
    if (skew>s->config.max_skew_us) {
        s->speech=(talking_detector_state_t){0};out.reason="UNALIGNED_INPUTS";return out;
    }
    if (s->have_previous && (ref->time_us<=s->last_reference_us || student->time_us<=s->last_student_us)) {
        s->speech=(talking_detector_state_t){0};out.reason="REPEATED_OR_OUT_OF_ORDER_INPUT";return out;
    }
    if (s->have_previous && (ref->time_us-s->last_reference_us>750000 || student->time_us-s->last_student_us>750000))
        s->speech=(talking_detector_state_t){0};
    s->last_reference_us=ref->time_us;s->last_student_us=student->time_us;s->have_previous=1;
    if (!s->ready) {
        out.decision=REF_CALIBRATING;out.reason="LECTURER_ONLY_CALIBRATION";
        if (ref->speech_votes<2 || ref->rms<4) { out.reason="WAITING_FOR_LECTURER_SPEECH";return out; }
        if (s->count<REFERENCE_CALIBRATION_MAX) {
            s->reference_power[s->count]=ref->rms*ref->rms;
            s->student_power[s->count]=student->rms*student->rms;++s->count;
        }
        out.calibration_pairs=s->count;
        if (s->count>=REFERENCE_CALIBRATION_MIN) {
            if (fit(s)) { out.decision=REF_BASELINE_READY;out.reason="BASELINE_READY"; }
            else out.reason="CALIBRATION_NEEDS_LEVEL_VARIATION";
        }
        return out; /* Calibration never emits a student-talking event. */
    }
    float expected_power=s->power_scale*ref->rms*ref->rms+s->noise_intercept;
    out.expected_rms=sqrtf(fmaxf(0,expected_power));
    out.threshold_rms=sqrtf(fmaxf(0,expected_power+s->residual_upper))*(1+s->config.relative_margin)+s->config.absolute_margin;
    unsigned votes=student->rms>out.threshold_rms ? student->speech_votes : 0;
    talking_event_t event=talking_detector_step(&s->speech,votes,student->rms,0,0);
    out.decision=event==TALKING_CONFIRMED ? REF_STUDENT_TALKING : event==TALKING_PENDING ? REF_PENDING : REF_NO_TALKING;
    out.reason=student->rms<=out.threshold_rms ? "WITHIN_LECTURER_BASELINE" :
        student->speech_votes<2 ? "EXCESS_WITHOUT_ENOUGH_SPEECH" : "EXCESS_SPEECH";
    out.hold=s->speech.active && s->speech.weak_blocks;
    return out;
}

const char *reference_decision_name(reference_decision_t d) {
    switch(d) {
        case REF_CALIBRATING:return "CALIBRATING";
        case REF_BASELINE_READY:return "BASELINE_READY";
        case REF_NO_TALKING:return "NO_STUDENT_TALKING";
        case REF_PENDING:return "SPEECH_PENDING";
        case REF_STUDENT_TALKING:return "STUDENT_TALKING";
        default:return "UNKNOWN";
    }
}

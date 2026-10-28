#include "reference_service.h"
#include "reference_detector.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

static reference_detector_t nodes[7];
static unsigned initialized,used,receiving,discarding;
static char command[256];

int reference_service_receiving(void) { return receiving; }

static int integer(const char *text,uint64_t *out) {
    if (!*text || *text<'0' || *text>'9') return 0;
    char *end;errno=0;*out=strtoull(text,&end,10);return !*end && errno!=ERANGE;
}

static int number(const char *text,float *out) {
    if (!*text) return 0;
    char *end;*out=strtof(text,&end);return !*end;
}

void reference_service_feed(int c,void (*write)(const char *,size_t)) {
    if (c=='@') { used=0;receiving=1;discarding=0;return; }
    if (!receiving) return;
    if (c=='\r') return;
    if (discarding) { if (c=='\n') receiving=0;return; }
    if (c!='\n') {
        if (used+1<sizeof(command)) command[used++]=(char)c;
        else { discarding=1;write("REF_ERROR,COMMAND_TOO_LONG\n",27); }
        return;
    }
    receiving=0;command[used]=0;
    if (!strcmp(command,"RESET")) {
        for (unsigned i=0;i<7;++i) reference_detector_init(&nodes[i]);
        initialized=1;write("REF_RESET,OK\n",13);return;
    }
    char *fields[11];unsigned count=1;fields[0]=command;
    for (char *p=command;*p;++p) if (*p==',') {
        *p=0;if (count>=11) { count=12;break; }fields[count++]=p+1;
    }
    uint64_t id,now,rt,rv,rf,st,sv,sf;float rr,sr;
    if (count!=11 || strcmp(fields[0],"PAIR") || !integer(fields[1],&id) || id<1 || id>7 ||
        !integer(fields[2],&now) || !integer(fields[3],&rt) || !number(fields[4],&rr) ||
        !integer(fields[5],&rv) || rv>3 || !integer(fields[6],&rf) || rf>1 ||
        !integer(fields[7],&st) || !number(fields[8],&sr) || !integer(fields[9],&sv) || sv>3 ||
        !integer(fields[10],&sf) || sf>1) {
        write("REF_ERROR,INVALID_PAIR\n",23);return;
    }
    if (!initialized) { for (unsigned i=0;i<7;++i) reference_detector_init(&nodes[i]);initialized=1; }
    reference_reading_t ref={rt,rr,(uint32_t)rv,(uint32_t)rf},student={st,sr,(uint32_t)sv,(uint32_t)sf};
    reference_detector_t *state=&nodes[id-1];
    reference_result_t out=reference_detector_update(state,&ref,&student,now);
    char line[384];
    int n=snprintf(line,sizeof(line),
        "REF_RESULT,NODE=%u,DECISION=%s,REASON=%s,CAL_PAIRS=%u,EXPECTED_RMS=%.3f,"
        "THRESHOLD_RMS=%.3f,STUDENT_RMS=%.3f,HOLD=%u,SCALE=%.7f,NOISE_POWER=%.3f\n",
        (unsigned)id,reference_decision_name(out.decision),out.reason,out.calibration_pairs,
        out.expected_rms,out.threshold_rms,sr,out.hold,state->power_scale,state->noise_intercept);
    if (n>0 && n<(int)sizeof(line)) write(line,(size_t)n);
}

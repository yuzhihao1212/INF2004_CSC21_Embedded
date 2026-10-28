"""Exercise the actual Pico C reference service with synthetic inputs."""
import math
from reference_nodes import NativeService, ClockAligner, pair_command, simulated_pairs


def main():
    service=NativeService()
    rows=[]
    for label,now,ref,student in simulated_pairs():
        line,=service.send(pair_command(1,now,ref,student))
        fields=dict(part.split('=',1) for part in line.split(',')[1:])
        rows.append((label,fields))
    assert all(r['DECISION']=='CALIBRATING' for _,r in rows[:19])
    assert rows[19][1]['DECISION']=='BASELINE_READY'
    teacher=rows[20][1]
    assert teacher['DECISION']=='NO_STUDENT_TALKING'
    assert abs(float(teacher['EXPECTED_RMS'])-math.sqrt(14500))<.01
    for label,r in rows:
        if label=='one cough-like positive block':assert r['DECISION']=='SPEECH_PENDING'
        if label in ('gap after cough','loud non-speech'):assert r['DECISION']=='NO_STUDENT_TALKING'
    assert [r['DECISION'] for label,r in rows if label=='additional sustained student speech']==['SPEECH_PENDING','STUDENT_TALKING']
    weak=next(r for label,r in rows if label=='one weak block during speech')
    assert weak['DECISION']=='STUDENT_TALKING' and weak['HOLD']=='1'
    assert [r['DECISION'] for label,r in rows if label=='student stops']==['STUDENT_TALKING','NO_STUDENT_TALKING']
    assert rows[-1][1]['DECISION']=='UNKNOWN'

    t=100000000
    def send(rms=150,votes=3,valid=True,ref_rms=150,ref_valid=True,node=1,now=None,rt=None,st=None):
        nonlocal t
        t+=500000
        ref=dict(time_us=t if rt is None else rt,rms=ref_rms,votes=3,valid=ref_valid)
        student=dict(time_us=t if st is None else st,rms=rms,votes=votes,valid=valid)
        line,=service.send(pair_command(node,t if now is None else now,ref,student))
        return dict(part.split('=',1) for part in line.split(',')[1:])
    # Stale / invalid / duplicate / skewed data must clear active persistence.
    for fault in ('invalid','stale','skew','replay','nan','future'):
        send(votes=0)
        send(votes=0)
        assert send()['DECISION']=='SPEECH_PENDING'
        assert send()['DECISION']=='STUDENT_TALKING'
        previous=t
        if fault=='invalid':result=send(valid=False)
        elif fault=='stale':result=send(now=t+2100000)
        elif fault=='skew':result=send(rt=t+200000,st=t+500000)
        elif fault=='replay':result=send(rt=previous,st=previous)
        elif fault=='nan':result=send(rms=float('nan'))
        else:result=send(rt=t+1000000,st=t+1000000)
        assert result['DECISION']=='UNKNOWN',(fault,result)
        assert send()['DECISION']=='SPEECH_PENDING',fault
        assert send()['DECISION']=='STUDENT_TALKING',fault
    # A gap must not bridge into another alert, even when samples are fresh.
    t+=1000000
    assert send()['DECISION']=='SPEECH_PENDING'
    # Each student owns its own calibration; reference silence remains valid.
    assert send(node=2)['DECISION']=='CALIBRATING'
    send(votes=0,ref_rms=0)
    send(votes=0,ref_rms=0)
    assert send(ref_rms=0)['DECISION']=='SPEECH_PENDING'
    assert send(ref_rms=0)['DECISION']=='STUDENT_TALKING'

    # Constant lecturer levels cannot identify gain and background separately.
    service.send('@RESET\n')
    for _ in range(64):result=send(rms=30,ref_rms=100)
    assert result['DECISION']=='CALIBRATING'
    assert result['REASON']=='CALIBRATION_NEEDS_LEVEL_VARIATION'
    assert service.send('@PAIR,8,1,1,1,3,1,1,1,3,1\n')==['REF_ERROR,INVALID_PAIR']
    assert service.send('@PAIR,1,1,1,1,3,1,1,1,3,1,extra\n')==['REF_ERROR,INVALID_PAIR']
    assert service.send('@PAIR,1,18446744073709551616,1,1,3,1,1,1,3,1\n')==['REF_ERROR,INVALID_PAIR']
    assert service.send('@'+'x'*300+'rsv\n')==['REF_ERROR,COMMAND_TOO_LONG']
    assert service.send('@RESET\n')==['REF_RESET,OK']
    assert send()['CAL_PAIRS']=='1'

    # Independent boot-time clocks align to the same PC monotonic clock.
    def fields(sender,window=1,**extra):
        return dict(DELIVERED_US=str(sender),WINDOW=str(window),WORK_US='470000',
            PROCESSING_US='465000',RMS_ADC='100',SPEECH_VOTES='3',
            OVERRUN='0',ADC_NEAR_RAIL='0',EVENT='TALKING',BUILD='timing-v7',**extra)
    a,b=ClockAligner(),ClockAligner()
    assert a.convert(fields(1000000),100000000)['time_us']==b.convert(fields(9000000),100000000)['time_us']
    assert not a.convert(fields(1500000,2),100500000)['reboot']
    assert a.convert(fields(500000,1),101000000)['reboot']
    assert not a.convert(dict(fields(1000000,2),EVENT='TIMING_FAULT'),101500000)['valid']
    assert not a.convert(dict(fields(1500000,3),ADC_NEAR_RAIL='80'),102000000)['valid']
    assert not a.convert(dict(fields(2000000,4),OVERRUN='1'),102500000)['valid']
    print('PASS: actual C calibration, louder lecturer, transient/noise gating, speech hold/release,')
    print('invalid/stale/skew/replay handling, independent nodes, parser recovery, USB clock alignment.')
    print('Synthetic logic tests only; no classroom accuracy or cough-classification estimate.')


if __name__=='__main__':main()

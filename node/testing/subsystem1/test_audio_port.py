"""Replay original and ported C, using a host gcc and no Python ML packages."""
from pathlib import Path
import subprocess,tempfile
from generate_dsp import reference_source
ROOT=Path(__file__).resolve().parents[3]
def main():
    sources=[
        ('firmware/audio/audio_dsp.c',['audio_dsp_init=reference_init','audio_dsp_process=reference_process']),
        ('firmware/audio/classifier/dsp_int8_candidate.c',['dsp_int8_predict=reference_predict']),
        ('firmware/audio/classifier/classifier_probabilities.c',['classifier_probabilities=reference_probabilities']),
        ('node/app_program/subsystem1/audio_dsp.c',[]),
        ('node/app_program/subsystem2/dsp_int8_candidate.c',[]),
        ('node/app_program/subsystem2/classifier_probabilities.c',[]),
        ('node/app_program/subsystem2/classifier_timing.c',[]),
        ('node/app_program/subsystem2/audio_inference.c',[]),
        ('node/testing/subsystem1/audio_replay.c',[])]
    with tempfile.TemporaryDirectory() as temp:
        reference=Path(temp)/'reference.c'
        reference.write_text(reference_source(),encoding='utf-8')
        sources[0]=(str(reference),sources[0][1])
        sources.insert(4,('firmware/audio/audio_dsp.c',['audio_dsp_init=standalone_init','audio_dsp_process=standalone_process']))
        objects=[]
        for i,(source,defines) in enumerate(sources):
            obj=str(Path(temp)/f'{i}.o'); objects.append(obj)
            subprocess.run(['gcc','-std=c11','-O2','-Wall','-Wextra','-Wno-missing-braces',
                '-I'+str(ROOT/'firmware/audio'),*['-D'+d for d in defines],'-c',str(ROOT/source),'-o',obj],check=True)
        exe=str(Path(temp)/'replay.exe')
        subprocess.run(['gcc',*objects,'-lm','-o',exe],check=True)
        subprocess.run([exe],check=True)
if __name__=='__main__': main()

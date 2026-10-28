"""Actually train a small local speech/non-speech head on frozen PulseVAD features.

No lecturer/conversation classes, no one-class trick, no claim of training the
pretrained backbone. Partition public data by speaker/original noise source.
"""
import hashlib
import json
from math import gcd
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from export_pulsevad import array, literal
from verify_pulsevad import load_c, ROOT


def source_weights(labels, sources):
    w = np.zeros(len(labels))
    for label in [0,1]:
        groups = np.unique(sources[labels==label])
        for source in groups:
            mask = (sources==source)&(labels==label)
            w[mask] = len(labels)/(2*len(groups)*mask.sum())
    return w


def metrics(part, predictions):
    return dict(examples=len(predictions), accuracy=float(np.mean(part['y']==predictions)),
                source_balanced_accuracy=float(np.average(part['y']==predictions,weights=part['weights'])),
                confusion_matrix=confusion_matrix(part['y'],predictions,labels=[0,1]).tolist(),
                labels=['non_speech','speech'])


def main():
    lib = load_c()
    folder = ROOT/'ml/data/vad_public'
    manifest = json.loads((folder/'manifest.json').read_text())
    dest = ROOT/'ml/candidates/talking_head'
    dest.mkdir(parents=True,exist_ok=True)
    rng = np.random.default_rng(42)
    rows = []
    source_splits = {}
    def add(wave, label, source, split, gain=1):
        assert source_splits.setdefault(source,split)==split
        assert len(wave)==3200
        adc = np.clip(np.rint(wave*gain*2048+2048),0,4095).astype(np.uint16)
        # Exact board frontend/embedding (not a Python approximation).
        embedding = np.empty(8,np.float32)
        probability = lib.pulsevad_process_adc(adc,embedding)
        rows.append(dict(x=embedding.copy(),y=label,source=source,split=split,base=probability))
    for entry in manifest['files']:
        path = folder/entry['file']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256']
        wave, rate = sf.read(path,dtype='float32')
        if wave.ndim>1:
            wave = wave.mean(axis=1)
        factor = gcd(rate,16000)
        wave = resample_poly(wave,16000//factor,rate//factor).astype(np.float32)
        wave -= wave.mean()
        if len(wave)<3200:
            wave = np.pad(wave,(0,3200-len(wave)))
        peak = max(float(np.max(np.abs(wave))),1e-6)
        # Independent randomized levels during training only. All classes use
        # the same peak range so volume is not a label shortcut.
        wave = wave/peak*.4
        starts = np.linspace(0,len(wave)-3200,min(5 if entry['label']==0 else 3,
                                                 max(1,len(wave)//3200)),dtype=int)
        chunks = [wave[s:s+3200] for s in starts]
        rms = np.array([np.sqrt(np.mean(c*c)) for c in chunks])
        for chunk, energy in zip(chunks,rms):
            # FSDD utterances are trimmed; reject quiet tails. These labels
            # remain utterance-derived, not hand-annotated frame boundaries.
            if entry['label']==1 and energy<max(rms.max()*.2,.002):
                continue
            gains = rng.uniform(.2,1.8,2) if entry['split']=='train' else [1.]
            for gain in gains:
                add(chunk,entry['label'],entry['source'],entry['split'],gain)
    # Synthetic negatives have independent random seeds/sources per split.
    for split in ['train','validation','test']:
        add(np.zeros(3200,np.float32),0,'synthetic:silence:'+split,split)
        for i in range(12):
            add(rng.normal(0,.005,3200),0,'synthetic:noise:'+split,split)
    data = {}
    for split in ['train','validation','test']:
        part = [r for r in rows if r['split']==split]
        data[split] = {key:np.asarray([r[key] for r in part]) for key in ['x','y','source','base']}
        data[split]['weights'] = source_weights(data[split]['y'],data[split]['source'])
    candidates, best = [], None
    for regularization in [.01,.1,1.]:
        model = make_pipeline(StandardScaler(),LogisticRegression(C=regularization,max_iter=2000))
        model.fit(data['train']['x'],data['train']['y'],
                  logisticregression__sample_weight=data['train']['weights'])
        score = metrics(data['validation'],model.predict(data['validation']['x']))
        candidates.append(dict(C=regularization,validation=score))
        if best is None or score['source_balanced_accuracy']>best[0]:
            best = (score['source_balanced_accuracy'],regularization,model)
    scaler, classifier = best[2].steps[0][1],best[2].steps[1][1]
    coef = classifier.coef_[0]/scaler.scale_
    bias = classifier.intercept_[0]-np.dot(coef,scaler.mean_)
    baseline = {s:metrics(data[s],data[s]['base']>=.5) for s in ['validation','test']}
    own = {s:metrics(data[s],best[2].predict(data[s]['x'])) for s in ['validation','test']}
    # Choose on validation only. Both outputs remain visible on USB.
    use_own = own['validation']['source_balanced_accuracy']>baseline['validation']['source_balanced_accuracy']+.01
    header = '\n\n'.join([
        '/* Trained by train_talking_head.py. Frozen PulseVAD backbone, local logistic head. */',
        '#ifndef MOSAIC_TALKING_HEAD_H\n#define MOSAIC_TALKING_HEAD_H',
        f'#define TALKING_USE_OWN_HEAD {int(use_own)}',
        array('talking_head_weights',coef),f'static const float talking_head_bias = {literal(bias)};',
        '#endif\n'])
    (ROOT/'firmware/audio/pulsevad/talking_head.h').write_text(header,encoding='ascii')
    (dest/'head.json').write_text(json.dumps(dict(weights=coef.tolist(),bias=float(bias),C=best[1]),indent=2)+'\n')
    np.savez_compressed(dest/'features.npz',**{f'{s}_{k}':v for s,p in data.items() for k,v in p.items()})
    report = dict(task='speech versus non-speech; TALKING is a local activity label',
                  trained_here='9-parameter logistic classification head',
                  pretrained='Frozen PulseVAD FP32 neural backbone; not retrained',
                  seed=42, source_splits=source_splits, candidates=candidates, selected_C=best[1],
                  pretrained_results=baseline,own_head_results=own,
                  deployed_default='own_head' if use_own else 'pretrained',
                  dataset_repositories=manifest['repositories'],
                  manifest_sha256=hashlib.sha256((folder/'manifest.json').read_bytes()).hexdigest(),
                  limitations=['Small public spoken-digit/noise subset; not classroom accuracy.',
                               'Speech frame labels inferred from trimmed utterances, not manually annotated.',
                               'Source separation applies to the local head; upstream pretrained exposure is unknown.',
                               'Does not identify students or separate lecturer speech.',
                               'Training audio: FSDD CC BY-SA 4.0; ESC-50 CC BY-NC with per-file credits.'])
    (dest/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    main()

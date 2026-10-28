"""Export the complete, pinned PulseVAD FP32 model and exact frontend tables.

The upstream weights-only C header omits biases; do not use it for inference.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
import onnx
from onnx import numpy_helper

ROOT = Path(__file__).resolve().parents[2]
COMMIT = 'af25e79d66830a3fee74541812721f6158fc92b5'


def literal(v):
    s = format(float(v), '.9g')
    return s + ('f' if '.' in s or 'e' in s else '.0f')


def array(name, values, kind='float'):
    flat = np.asarray(values).reshape(-1)
    fmt = literal if kind == 'float' else lambda v: str(int(v))
    lines = [f'static const {kind} {name}[{len(flat)}] = {{']
    for i in range(0, len(flat), 8):
        lines.append('    ' + ', '.join(fmt(v) for v in flat[i:i+8]) + ',')
    return '\n'.join(lines + ['};'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', type=Path, required=True)
    args = parser.parse_args()
    upstream = args.upstream
    actual_commit = subprocess.check_output(['git','-C',str(upstream),'rev-parse','HEAD'],text=True).strip()
    if actual_commit != COMMIT:
        raise ValueError(f'Expected pinned PulseVAD commit {COMMIT}, got {actual_commit}')
    data = upstream / 'pulsevad/data'
    dest = ROOT / 'firmware/audio/pulsevad/vendor'
    dest.mkdir(parents=True, exist_ok=True)
    model = onnx.load(data / 'pulsevad_2.1k.onnx')
    onnx.checker.check_model(model)
    tensors = {v.name: numpy_helper.to_array(v) for v in model.graph.initializer}
    shapes = {'adapter':(12,64,1),'conv0_dw':(12,1,11),'conv0_pw':(8,12,1),
              'block1':(8,8,1),'block2':(8,8,1),'subA_dw':(8,1,17),
              'subA_pw':(8,8,1),'subC_dw':(8,1,17),'subC_pw':(8,8,1),
              'skip':(8,8,1),'conv4_dw':(8,1,29),'conv4_pw':(8,8,1),
              'conv5':(8,8,1),'classifier':(2,8)}
    expected = {}
    for name,shape in shapes.items():
        expected[name+'.weight'] = shape
        if not name.endswith('_dw'):
            expected[name+'.bias'] = (shape[0],)
    assert {k:v.shape for k,v in tensors.items()} == expected, 'Unsupported CNN dimensions'
    header = ['/* Complete upstream pretrained FP32 weights, including folded biases. */',
              '#ifndef MOSAIC_PULSEVAD_MODEL_H', '#define MOSAIC_PULSEVAD_MODEL_H']
    for name, values in tensors.items():
        header.append(array('pv_' + name.replace('.', '_'), values))
    header.append('#endif\n')
    (dest / 'pulsevad_model.h').write_text('\n\n'.join(header), encoding='ascii')
    fb = np.load(data / 'mel_filterbank.npy')
    assert fb.shape == (257, 64)
    starts, counts, offsets, coefficients = [], [], [0], []
    for band in range(64):
        nz = np.flatnonzero(fb[:, band])
        assert len(nz) and np.array_equal(nz, np.arange(nz[0], nz[-1]+1))
        starts.append(nz[0]); counts.append(len(nz))
        coefficients.extend(fb[nz, band]); offsets.append(len(coefficients))
    tables = ['#ifndef MOSAIC_PULSEVAD_TABLES_H', '#define MOSAIC_PULSEVAD_TABLES_H',
              array('pv_hann', .5-.5*np.cos(2*np.pi*np.arange(400)/400)),
              array('pv_cos', np.cos(2*np.pi*np.arange(256)/512)),
              array('pv_sin', np.sin(2*np.pi*np.arange(256)/512)),
              array('pv_mel_start', starts, 'unsigned short'),
              array('pv_mel_count', counts, 'unsigned short'),
              array('pv_mel_offset', offsets, 'unsigned short'),
              array('pv_mel_coeff', coefficients), '#endif\n']
    (dest / 'pulsevad_tables.h').write_text('\n\n'.join(tables), encoding='ascii')
    for name in ['pulsevad_2.1k.onnx', 'mel_filterbank.npy']:
        shutil.copyfile(data / name, dest / name)
    shutil.copyfile(upstream / 'LICENSE', dest / 'LICENSE')
    shutil.copyfile(upstream / 'pulsevad/frontend_np.py', dest / 'frontend_np.py')
    manifest = dict(repository='https://github.com/AydinAdnan/PulseVAD', commit=COMMIT,
                    format='FP32 complete model, not the incomplete INT8 C header',
                    files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in sorted(dest.iterdir()) if p.is_file() and p.name != 'SOURCE.json'})
    (dest / 'SOURCE.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print('Exported complete model and sparse frontend tables:', dest)


if __name__ == '__main__':
    main()

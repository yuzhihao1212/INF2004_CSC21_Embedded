"""Prepare two public cough clips for the virtual audio demo (no training).

Requires the existing pinned ESC-50 metadata from fetch_vad_audio.py.
Audio is ESC-50 CC BY-NC; keep its licence and per-source metadata.
"""
import csv
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def main():
    data = ROOT/'ml/data/vad_public'
    if not (data/'sources.json').exists() or not (data/'esc50.csv').exists():
        raise SystemExit('Run ml/scripts/fetch_vad_audio.py first to prepare pinned public audio/metadata.')
    commit = json.loads((data/'sources.json').read_text())['karolpiczak/ESC-50']
    with (data/'esc50.csv').open() as source:
        rows = [r for r in csv.DictReader(source) if r['category']=='coughing' and r['fold']=='5'][:2]
    if len(rows) != 2:raise RuntimeError('Expected two cough sources in pinned metadata')
    folder = data/'virtual_audio'
    folder.mkdir(parents=True, exist_ok=True)
    entries = []
    for row in rows:
        url = f"https://raw.githubusercontent.com/karolpiczak/ESC-50/{commit}/audio/{row['filename']}"
        path = folder/row['filename']
        if not path.exists():
            with urllib.request.urlopen(url, timeout=30) as response:payload = response.read()
            if payload[:4] != b'RIFF':raise RuntimeError('Expected WAV download')
            path.write_bytes(payload)
        entries.append(dict(file=path.relative_to(data).as_posix(), category='coughing', url=url,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source=row,
            license='ESC-50 CC BY-NC; see ../ESC50_LICENSE',
            purpose='Virtual audio demonstration, not training or a held-out accuracy estimate'))
    (folder/'manifest.json').write_text(json.dumps(entries, indent=2)+'\n')
    print('Prepared', len(entries), 'cough recordings with provenance:', folder)


if __name__ == '__main__':main()

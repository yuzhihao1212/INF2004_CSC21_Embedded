"""Fetch a bounded public speech/non-speech subset, with source-level splits.

FSDD speech: CC BY-SA 4.0. ESC-50 non-speech: CC BY-NC (retain per-file credits).
These are speech-presence labels, not classroom conversation labels.
"""
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / 'ml/data/vad_public'


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'MOSAIC-VAD-research'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    config = DEST / 'sources.json'
    if config.exists():
        commits = json.loads(config.read_text())
    else:
        commits = {}
        for repo in ['Jakobovski/free-spoken-digit-dataset', 'karolpiczak/ESC-50']:
            commits[repo] = json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/master'))['sha']
        config.write_text(json.dumps(commits,indent=2)+'\n')
    def url(repo, path):
        return f'https://raw.githubusercontent.com/{repo}/{commits[repo]}/{path}'
    fsdd, esc = commits.keys()
    for repo, name in [(fsdd,'FSDD_README.md'),(esc,'ESC50_README.md')]:
        (DEST/name).write_bytes(fetch(url(repo,'README.md')))
    (DEST/'ESC50_LICENSE').write_bytes(fetch(url(esc,'LICENSE')))
    rows = list(csv.DictReader(io.StringIO(fetch(url(esc,'meta/esc50.csv')).decode())))
    (DEST/'esc50.csv').write_bytes(fetch(url(esc,'meta/esc50.csv')))
    entries = []
    # Speakers cannot cross partitions. This differs from FSDD's digit task split.
    splits = {'jackson':'train', 'nicolas':'train', 'theo':'train',
              'yweweler':'validation', 'george':'test', 'lucas':'test'}
    for speaker, split in splits.items():
        for digit in range(10):
            for take in [5,6,7]:
                name = f'{digit}_{speaker}_{take}.wav'
                entries.append(dict(file=f'speech/{name}', url=url(fsdd,f'recordings/{name}'),
                                    label=1, source=f'fsdd:{speaker}', split=split,
                                    license='CC BY-SA 4.0'))
    categories = ['rain','wind','clock_tick','keyboard_typing','door_wood_knock',
                  'washing_machine','vacuum_cleaner','engine','crackling_fire','footsteps']
    for category in categories:
        for fold in range(1,6):
            matches = sorted([r for r in rows if r['category']==category and int(r['fold'])==fold],
                             key=lambda r:r['filename'])[:2]
            assert len(matches)==2, (category,fold)
            for r in matches:
                split = 'train' if fold<=2 else 'validation' if fold==3 else 'test'
                entries.append(dict(file=f"noise/{r['filename']}", url=url(esc,f"audio/{r['filename']}"),
                                    label=0, source=f"esc:{r['src_file']}", split=split,
                                    category=category, license='ESC-50 CC BY-NC; see ESC50_LICENSE'))
    def download(entry):
        path = DEST/entry['file']
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            payload = fetch(entry['url'])
            assert payload[:4] == b'RIFF', entry['url']
            path.write_bytes(payload)
        entry['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        return entry
    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(download, entries))
    groups = {}
    for row in entries:
        assert groups.setdefault(row['source'],row['split']) == row['split']
    manifest = dict(repositories=commits, files=entries,
                    purpose='Small speech/non-speech transfer-head experiment; not conversation recognition.')
    (DEST/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Saved',len(entries),'source files:',DEST,flush=True)


if __name__ == '__main__':
    main()

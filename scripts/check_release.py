#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json, re, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
issues=[]
rows=list(csv.DictReader((ROOT/'data'/'certified-results.csv').open()))
if len(rows)!=44:issues.append(f'certified-results rows={len(rows)} expected=44')
cert_dirs=sorted((ROOT/'certifiers').glob('n*'))
if len(cert_dirs)!=44:issues.append(f'certifier dirs={len(cert_dirs)} expected=44')
for d in cert_dirs:
 for m in ('spectral','componentwise'):
  if not (d/f'{m}.py').is_file():issues.append(f'missing {d.name}/{m}.py')
rep=json.loads((ROOT/'evidence'/'full-cleanroom-replay'/'PUBLIC_REPO_FULL_REPLAY.json').read_text())
if rep.get('verifier_count')!=88 or rep.get('certified_count')!=88 or rep.get('failed_count')!=0:issues.append('full clean-room replay is not 88/88')
for r in rep['results']:
 p=ROOT/r['repo_relative_script']
 if not p.is_file():issues.append(f'missing replay script {p.relative_to(ROOT)}');continue
 h=hashlib.sha256(p.read_bytes()).hexdigest()
 if h!=r['script_sha256']:issues.append(f'replay script hash mismatch {p.relative_to(ROOT)}')
for bad in ROOT.rglob('*'):
 if bad.is_file() and (bad.suffix=='.pyc' or '__pycache__' in bad.parts):issues.append(f'bytecode present: {bad.relative_to(ROOT)}')
print(f'certified_rows={len(rows)} certifier_dirs={len(cert_dirs)} replay={rep.get("certified_count")}/88 issues={len(issues)}')
if issues:
 print('\n'.join(issues));sys.exit(1)

#!/usr/bin/env python3
from __future__ import annotations
import csv, hashlib, json, re, sys
from pathlib import Path
sys.dont_write_bytecode=True
from certificate_lib import EXPECTED_NS, METHODS, certifier_relpath  # noqa: E402
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
# The three counters above are only what the replay says about itself; the
# records must each be a success, and together exactly the 88 published scripts.
expected_scripts={certifier_relpath(n,m) for n in EXPECTED_NS for m in METHODS}
if len(expected_scripts)!=88:issues.append(f'expected script set has {len(expected_scripts)} entries, expected 88')
if len(rep['results'])!=88:issues.append(f'full clean-room replay has {len(rep["results"])} records, expected 88')
recorded=[r.get('repo_relative_script') for r in rep['results']]
for s in sorted({s for s in recorded if recorded.count(s)>1}):issues.append(f'duplicate replay record {s}')
for s in sorted(expected_scripts-set(recorded)):issues.append(f'no replay record for {s}')
for s in sorted(set(recorded)-expected_scripts,key=str):issues.append(f'unexpected replay record {s}')
for r in rep['results']:
 name=r.get('repo_relative_script')
 if r.get('status')!='CERTIFIED':issues.append(f'replay record {name} status={r.get("status")!r}, expected CERTIFIED')
 if type(r.get('return_code')) is not int or r.get('return_code')!=0:issues.append(f'replay record {name} return_code={r.get("return_code")!r}, expected 0')
 if r.get('timed_out') is not False:issues.append(f'replay record {name} timed_out={r.get("timed_out")!r}, expected false')
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

#!/usr/bin/env python3
from __future__ import annotations
import argparse, concurrent.futures, csv, json, re, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATUS_RE=re.compile(r"(?im)^\s*(?:status\s*[:=]\s*)?CERTIFIED\s*$|status\s*[:=]\s*CERTIFIED")
p=argparse.ArgumentParser()
g=p.add_mutually_exclusive_group(required=True)
g.add_argument('--quick',action='store_true')
g.add_argument('--all',action='store_true')
p.add_argument('--jobs',type=int,default=1)
p.add_argument('--timeout',type=int,default=300)
p.add_argument('--output-dir',type=Path)
a=p.parse_args()
ns=[14,15,21,36,52] if a.quick else sorted(int(x.name[1:]) for x in (ROOT/'certifiers').glob('n*'))
jobs=[(n,m,ROOT/'certifiers'/f'n{n:02d}'/f'{m}.py') for n in ns for m in ('spectral','componentwise')]
if a.output_dir: a.output_dir.mkdir(parents=True,exist_ok=True)
def run(j):
 n,m,s=j;t=time.perf_counter()
 try:
  q=subprocess.run([sys.executable,s.name],cwd=s.parent,text=True,capture_output=True,timeout=a.timeout)
  out,err,rc,to=q.stdout,q.stderr,q.returncode,False
 except subprocess.TimeoutExpired as e:
  out=e.stdout or '';err=e.stderr or '';rc=124;to=True
  if isinstance(out,bytes):out=out.decode(errors='replace')
  if isinstance(err,bytes):err=err.decode(errors='replace')
 elapsed=time.perf_counter()-t
 certified=rc==0 and not to and bool(STATUS_RE.search(out))
 r={'n':n,'method':m,'return_code':rc,'timed_out':to,'certified':certified,'elapsed_seconds':round(elapsed,6)}
 if a.output_dir:
  stem=f'n{n:02d}_{m}';(a.output_dir/f'{stem}.stdout.txt').write_text(out);(a.output_dir/f'{stem}.stderr.txt').write_text(err);(a.output_dir/f'{stem}.json').write_text(json.dumps(r,indent=2))
 return r,out,err
results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,a.jobs)) as ex:
 for f in concurrent.futures.as_completed([ex.submit(run,j) for j in jobs]):
  r,out,err=f.result();results.append(r);print(f"n={r['n']} {r['method']} rc={r['return_code']} certified={r['certified']} elapsed={r['elapsed_seconds']:.2f}",flush=True)
  if not r['certified']:
   print(out);print(err,file=sys.stderr)
results.sort(key=lambda x:(x['n'],x['method']))
if a.output_dir:
 fields=list(results[0]);
 with (a.output_dir/'summary.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(results)
 (a.output_dir/'summary.json').write_text(json.dumps({'verifier_count':len(results),'certified_count':sum(x['certified'] for x in results),'results':results},indent=2))
raise SystemExit(1 if any(not x['certified'] for x in results) else 0)

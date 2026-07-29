#!/usr/bin/env python3
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument('--n',type=int,required=True)
p.add_argument('--method',choices=['spectral','componentwise','both'],default='both')
a=p.parse_args()
methods=['spectral','componentwise'] if a.method=='both' else [a.method]
for m in methods:
    s=ROOT/'certifiers'/f'n{a.n:02d}'/f'{m}.py'
    if not s.exists(): raise SystemExit(f'No certified verifier: {s}')
    print(f'== n={a.n} {m} ==',flush=True)
    rc=subprocess.call([sys.executable,str(s)],cwd=str(s.parent))
    if rc: raise SystemExit(rc)

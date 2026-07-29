#!/usr/bin/env python3
from pathlib import Path
import hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'SHA256SUMS'
bad=[];count=0
for line in p.read_text().splitlines():
 if not line.strip(): continue
 h,rel=line.split('  ',1);q=ROOT/rel;count+=1
 if not q.is_file() or hashlib.sha256(q.read_bytes()).hexdigest()!=h: bad.append(rel)
print(f'checked={count} bad={len(bad)}')
if bad: print('\n'.join(bad));sys.exit(1)

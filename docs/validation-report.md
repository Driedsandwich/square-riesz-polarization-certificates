# Validation report for v1.0.0

## Structural and package checks

- Certified configurations: **44** (`n=7,8,10,11,12` and `n=14..52`).
- Explicit no-improvement rows: **n=9, n=13**.
- Each certified configuration has exactly two certifier scripts.
- Coordinate count equals `n`: **PASS for all 44 configurations**.
- All source coordinates lie in `[0,1]^2`: **PASS**.
- Exact duplicate source coordinates: **0 for every certified configuration**.
- Certified lower bound does not exceed the rigorous upper witness: **PASS**.
- Canonical saved replay logs report `CERTIFIED` for all 88 verifier instances.

## Full public-repository clean-room replay

A clean copy of the public release candidate was extracted to a new directory. All 88 certifier scripts were executed from that copy with Python 3.13.5 and `PYTHONHASHSEED=0`.

- Verifiers executed: **88**.
- Return code 0 and `CERTIFIED`: **88/88**.
- Failures or timeouts: **0**.
- Workers: **4**.
- Sum of verifier runtimes: **1901.194 seconds**.

Every certifier script hash in the replay record matches the script shipped in this release. Full logs and machine-readable metadata are in `evidence/full-cleanroom-replay/`.

## Trust boundary

This validates reproducibility of the included fixed-configuration lower-bound certificates. It does not establish global optimality, exhaustive novelty, or formal completeness of the numerical local-minimum lists.

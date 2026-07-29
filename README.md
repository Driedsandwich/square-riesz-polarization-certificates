# Certified lower bounds for unit-square Riesz 2-polarization

## Origin and problem statement

This project concerns Erich Friedman's **“Maximizing Minimum Light Intensity”** problem, published at [Erich's Packing Center](https://erich-friedman.github.io/packing/light/).

Place \(n\) unit point lights at positions \(X=\{x_1,\ldots,x_n\}\subset[0,1]^2\) in the unit square. The illumination at a point \(p\) is the inverse-square sum

$$
U_X(p)=\sum_{i=1}^n \frac{1}{\|p-x_i\|^2},
$$

and the fixed-configuration minimum intensity is

$$
I(X)=\min_{p\in[0,1]^2} U_X(p).
$$

The original max-min problem asks for the largest possible value of \(I(X)\) over all \(n\)-point configurations \(X\). Friedman's page records best-known numerical configurations and displayed lower-bound values for this problem.

This repository has a narrower, proof-oriented role: it supplies exact-rational lower-bound certificates for specified **fixed finite-decimal configurations**. Certifying a fixed configuration does not prove that the configuration is globally optimal among all placements, and a certified value is not automatically an official record-board value. This repository is independent and is not affiliated with or endorsed by Erich Friedman.

## Canonical publication

The canonical repository and `v1.0.0` Release URLs are recorded in `PUBLICATION_STATUS.md` during publication finalization.

This repository contains reproducible **lower-bound certificates for fixed point configurations** in the unit square. For a configuration $X=\{x_1,\ldots,x_n\}\subset[0,1]^2$,

$$
I(X)=\min_{p\in[0,1]^2}\sum_{i=1}^n \frac{1}{\|p-x_i\|^2}.
$$

The release includes certified fixed configurations for **44 values of $n$**: `7, 8, 10, 11, 12`, and every `n` from `14` through `52`. For `n=9` and `n=13`, completed searches reproduced the known numerical basins but did not establish an improvement.

## What is certified

For each exact finite-decimal configuration in `data/configurations/`, both included verifiers establish the stated continuous lower bound over the unit square:

1. `certifiers/nXX/spectral.py` — a second-order Taylor lower bound using a lower Hessian-eigenvalue bound.
2. `certifiers/nXX/componentwise.py` — componentwise exact rational intervals for `H_xx`, `H_yy`, and `H_xy`.

The methods use different rigorous second-order remainder estimates, but share the fixed coordinates, exact rational arithmetic, and branch-and-bound framework. They are not represented as fully independent proof systems.

## Claim boundary

The release proves statements of the form:

> For the exact coordinates supplied for a fixed configuration, the continuous minimum over the full unit square is at least the stated lower bound.

It does **not** prove global optimality over all configurations, exhaustive worldwide novelty, or official-record status for internal configurations.

## Reproduce

Python 3.13 and the standard library are sufficient for the exact certifiers.

```bash
python scripts/verify_manifest.py
python scripts/verify_one.py --n 15 --method both
python scripts/verify_all.py --quick --jobs 2
python scripts/verify_all.py --all --jobs 2 --output-dir replay-output
```

The full release replay executed all **88 verifiers** (44 configurations × 2 methods) from a freshly extracted copy of the public repository. Result: **88/88 returned code 0 and `CERTIFIED`**. See `evidence/full-cleanroom-replay/`.

The release reproduces and verifies the certificates, not the original exploratory search process. Optimization/search code, random seeds, and complete search transcripts are not included in v1.0.0.

## Data

- `data/certified-results.csv` and `.json`: certified lower bounds, upper witnesses, structure, and internal/external status.
- `data/configurations/nXX/`: exact source coordinates.
- `data/non-improvement-results.csv`: `n=9` and `n=13` search outcomes.
- `all_local_minima_count` in the result tables: numerical counts where available; full local-minimum coordinate lists are not included and are not proof inputs.
- `evidence/saved-replays/`: canonical saved replay logs.
- `evidence/full-cleanroom-replay/`: clean-room replay logs for all 88 public certifier scripts.

## Relationship to the original record board

The original “Maximizing Minimum Light Intensity” board is maintained by Erich Friedman. Some configurations and lower bounds for `n<=36` were communicated to the maintainer, and the public board may display earlier submitted values.

The latest certified values in this repository can exceed values that were previously submitted or displayed. The result table and `docs/supersession-map.md` keep submitted, observed-board, and current repository values distinct.

Configurations for `n>36` are independent, unsubmitted extensions. In every range, `CERTIFIED` means that the exact fixed finite-decimal configuration has the stated continuous lower bound; it does **not** mean that the value is an official record or that the configuration is globally optimal.

## Attribution and provenance

Candidate generation and certificate construction were performed using GPT-5.6 Sol Pro in ChatGPT browser mode. Driedsandwich supervised the research, coordinated audits and external communication, and prepared this release. The initial `n=14,15` package was additionally replayed with Codex under the submitter's supervision.

See `NOTICE.md`, `docs/claim-boundaries.md`, `docs/external-status.md`, `docs/methodology.md`, `docs/references.md`, and `docs/reproducibility.md`.

## Licenses

- Code: BSD-3-Clause — `LICENSE-CODE`.
- Original data and documentation: CC BY 4.0 — `LICENSE-DATA-DOCS.md`.

Third-party webpages, images, and private correspondence are not included.

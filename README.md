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

The canonical repository, the rule for which Release is currently canonical, the preserved `v1.0.0` snapshot, the asset names and the checksum interpretation are recorded in `PUBLICATION_STATUS.md`. A release carries two canonical distribution assets — the deterministic ZIP and its `.sha256` companion — plus a publication-attestation asset that records the measured release facts. Asset digests are resolved against the GitHub Release and that attestation asset, not against files in this tree; release titles and notes are description, not authority.

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
python -B -m unittest discover -s tests
python -B scripts/check_frozen_corpus.py \
  --expect-base-version v1.0.1 \
  --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 \
  --require-git-anchor
python -B scripts/verify_manifest.py
python -B scripts/check_release.py
python -B scripts/check_semantic_consistency.py
python -B scripts/regenerate_certified_results.py --check
python -B scripts/audit_upper_witness.py
python -B scripts/verify_one.py --n 15 --method both
python -B scripts/verify_all.py --quick --jobs 2
python -B scripts/verify_all.py --all --jobs 2 --output-dir replay-output
python -B scripts/validate_replay_output.py replay-output --expect-all
```

`--output-dir` must name a directory that does not exist or is empty, so stale
logs cannot be mistaken for a new run. `validate_replay_output.py` re-derives
the result from the written files — recomputing each certifier's SHA-256 and
re-classifying each log — instead of trusting the summary the run wrote about
itself. `docs/reproducibility.md` sets out what each layer of checking does and
does not establish.

`-B` keeps the tree free of `__pycache__`, which `scripts/check_release.py`
treats as a packaging defect. The replay scripts refuse to run under `python -O`
or `PYTHONOPTIMIZE`, because that would disable the `assert` statements each
certifier uses to re-check its own certificate.

The full release replay executed all **88 verifiers** (44 configurations × 2 methods) from a freshly extracted copy of the public repository. Result: **88/88 returned code 0 and `CERTIFIED`**. See `evidence/full-cleanroom-replay/`.

The releases reproduce and verify the certificates, not the original exploratory search process. Optimization/search code, random seeds, and complete search transcripts are not included in `v1.0.0`, `v1.0.1`, or `v1.0.2`. Which Release is currently canonical is resolved against GitHub, as `PUBLICATION_STATUS.md` explains.

`SHA256SUMS` covers the exact certificate and reproducibility corpus defined by `MANIFEST_POLICY.json`. The complete published snapshot is protected separately by the canonical Release ZIP SHA-256. See `docs/manifest-policy.md`.

## Data

- `data/certified-results.csv` and `.json`: certified lower bounds, upper witnesses, structure, and internal/external status. Both files are generated by `scripts/regenerate_certified_results.py` and must not be edited by hand; see `docs/data-schema.md` for the field definitions and the outward rounding policy for `rigorous_upper_witness`.
- `data/results-metadata.json`: the per-configuration values that are not computable from the corpus (provenance prose, submitted figure, local-minima count, descriptive minimum separation, presentation precision).
- `data/configurations/nXX/`: exact source coordinates.
- `data/non-improvement-results.csv`: `n=9` and `n=13` search outcomes.
- `all_local_minima_count` in the result tables: numerical counts where available; full local-minimum coordinate lists are not included and are not proof inputs.
- `evidence/saved-replays/`: canonical saved replay logs.
- `evidence/full-cleanroom-replay/`: clean-room replay logs for all 88 public certifier scripts.

## Relationship to the original record board

The original “Maximizing Minimum Light Intensity” board is maintained by Erich Friedman. Some configurations and lower bounds for `n<=36` were communicated to the maintainer, and the public board may display earlier submitted values.

The latest certified values in this repository can exceed values that were previously submitted or displayed. The result table and `docs/supersession-map.md` keep submitted, observed-board, and current repository values distinct.

Configurations for `n>36` are independent, unsubmitted extensions. In every range, `CERTIFIED` means that the exact fixed finite-decimal configuration has the stated continuous lower bound; it does **not** mean that the value is an official record or that the configuration is globally optimal.

Direct submissions to the original record board stopped at `n=36` following the maintainer's request to pause further batches while the existing submissions were processed. The current repository extends independently through `n=52`. That endpoint is the scope boundary of the internally audited public corpus, not a mathematical cutoff; configurations beyond `n=52` may still be searched for and certified.

## Attribution and provenance

Candidate generation and certificate construction were performed using GPT-5.6 Sol Pro in ChatGPT browser mode. Driedsandwich supervised the research, coordinated audits and external communication, and prepared this release. The initial `n=14,15` package was additionally replayed with an independent development environment under the submitter's supervision.

See `NOTICE.md`, `docs/claim-boundaries.md`, `docs/external-status.md`, `docs/manifest-policy.md`, `docs/methodology.md`, `docs/references.md`, and `docs/reproducibility.md`.

## Licenses

- Code: BSD-3-Clause — `LICENSE-CODE`.
- Original data and documentation: CC BY 4.0 — `LICENSE-DATA-DOCS.md`.

Third-party webpages, images, and private correspondence are not included.

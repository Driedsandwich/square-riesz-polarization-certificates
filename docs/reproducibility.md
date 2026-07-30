# Reproducibility

## Scope

The release reproduces and verifies the certificates, not the original exploratory search process. Optimization/search code, random seeds, and complete search transcripts are not included in v1.0.0.

## Integrity layers

`SHA256SUMS` covers the exact certificate and reproducibility corpus defined by `MANIFEST_POLICY.json`: certifiers, mathematical data, replay evidence, verification scripts, version metadata, and license files. Human-facing documentation and GitHub automation are intentionally outside that internal manifest.

The complete published Release ZIP, including documentation and automation files, is protected separately by the ZIP's external SHA-256 checksum. See `docs/manifest-policy.md`.

Regenerate and verify the internal manifest with:

```bash
python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
```

## Exact certifiers

The exact lower-bound certifiers require Python 3.13 and the standard library only. Each script embeds the exact finite-decimal source coordinates as rational numbers and performs a rational branch-and-bound proof.

```bash
python scripts/verify_manifest.py
python scripts/verify_one.py --n 32 --method both
python scripts/verify_all.py --all --jobs 2 --output-dir replay-output
```

`verify_all.py` records one stdout file, one stderr file, one metadata JSON file per verifier, plus CSV/JSON/Markdown summaries when `--output-dir` is supplied.

## Expected cost

In the v1.0.0 release replay, all 88 verifiers completed successfully. Individual runtimes varied from roughly one second to about one minute on the release-preparation environment. Parallel execution changes wall-clock time but not the proof result.

## Numerical analysis data

Candidate generation and local-minimum enumeration used optional scientific-Python dependencies listed in `requirements-analysis.txt`. These numerical analyses are not proof dependencies. The result table includes numerical local-minimum counts where available; full local-minimum coordinate lists are not included in v1.0.0. The exact lower-bound certificates do not rely on those counts.

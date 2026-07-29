# Reproducibility

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

Candidate generation and local-minimum enumeration use optional scientific-Python dependencies listed in `requirements-analysis.txt`. These numerical analyses are not proof dependencies. The exact lower-bound certificates do not rely on the supplied local-minimum lists.

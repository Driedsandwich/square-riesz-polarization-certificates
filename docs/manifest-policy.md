# Manifest policy

## Purpose

`SHA256SUMS` is the internal integrity manifest for the exact certificate and reproducibility corpus. Its scope is defined mechanically by `MANIFEST_POLICY.json`.

The internal manifest covers:

- `certifiers/`
- `data/`
- `evidence/`
- `scripts/`
- `MANIFEST_POLICY.json`
- `VERSION`
- the code and data/documentation license files

Human-facing documentation, GitHub workflow files, Issue and PR templates, and other repository-operation metadata are intentionally outside the internal manifest. Those files remain protected as part of the complete published Release ZIP by the ZIP's external SHA-256 checksum and the immutable GitHub Release snapshot.

This two-layer design separates two distinct integrity questions:

1. Has the exact mathematical and reproducibility corpus changed?
2. Is the complete published Release archive byte-for-byte identical to the canonical asset?

## Regeneration

Run the deterministic generator and verifier from the repository root:

```bash
python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
python scripts/check_release.py
```

`verify_manifest.py` rejects missing entries, unexpected entries, duplicate paths, unsafe paths, malformed SHA-256 values, and content-hash mismatches.

## Change control

Changes to `MANIFEST_POLICY.json`, the manifest generator, the verifier, any included proof input, any certifier, or any replay evidence require regeneration of `SHA256SUMS` and successful verification before merge.

Documentation-only and GitHub-automation-only changes do not require manifest regeneration unless they also modify a path included by the policy.

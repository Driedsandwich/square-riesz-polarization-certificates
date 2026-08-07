# Manifest policy

## Purpose

`SHA256SUMS` is the internal integrity manifest for the exact certificate and reproducibility corpus. Its scope is defined mechanically by `MANIFEST_POLICY.json`.

The internal manifest covers:

- `certifiers/`
- `data/`
- `evidence/`
- `scripts/`
- `tests/`
- `MANIFEST_POLICY.json`
- `VERSION`
- the code and data/documentation license files

`tests/` is inside the manifest because the regression and mutation tests are
what keep the checking scripts honest: a silently weakened test would leave the
corpus unprotected without changing any file the manifest otherwise covers.

Human-facing documentation, GitHub workflow files, Issue and PR templates, and other repository-operation metadata are intentionally outside the internal manifest. Those files remain protected as part of the complete published Release ZIP by the ZIP's external SHA-256 checksum and the immutable GitHub Release snapshot.

This two-layer design separates two distinct integrity questions:

1. Has the exact mathematical and reproducibility corpus changed?
2. Is the complete published Release archive byte-for-byte identical to the canonical asset?

## End-of-line protection

`SHA256SUMS` records the SHA-256 of the **bytes in the working tree**, so any
end-of-line conversion by Git breaks manifest verification. `.gitattributes`
therefore sets `* -text`, which disables that conversion for every path.

This was measured, not assumed. With only a `whitespace=cr-at-eol` attribute, a
clone with `core.autocrlf=true` stored the CRLF `data/certified-results.csv` as
an LF blob and checked several other manifest files out with different bytes,
and `core.autocrlf=input` produced an LF working-tree file. With `* -text`, all
sampled manifest files round-tripped byte-for-byte under `core.autocrlf` set to
`false`, `true` and `input`. `tests/test_followup_hardening.py` runs that
round trip against temporary repositories, together with a control that fails
if the check could not detect a conversion.

`-text` changes no stored bytes; it only stops Git from rewriting them.

## Regeneration

Run the deterministic generator and verifier from the repository root:

```bash
python scripts/regenerate_manifest.py
python scripts/verify_manifest.py
python scripts/check_release.py
```

`verify_manifest.py` rejects missing entries, unexpected entries, duplicate paths, unsafe paths, malformed SHA-256 values, and content-hash mismatches.

## The frozen corpus is pinned separately

`SHA256SUMS` is regenerated whenever the repository changes, so it cannot
distinguish a maintenance patch from an edit to a certifier. The 531 files that
carry the mathematics are pinned to the raw objects of the `v1.0.1` commit
`d92992101ca45a5cd755b8d962652ab7e4329973`, which `scripts/check_frozen_corpus.py`
reads directly — with `git replace` disabled — and checks first in both workflows,
by content, file type and Git mode.
`data/frozen-corpus-v1.0.1.sha256` is a readable mirror of those blobs, not an
authority of its own: it is a file in the repository and can be edited in the same
change as the corpus, which is why the release objects are compared as well. See
`docs/frozen-corpus.md`.

## Change control

Changes to `MANIFEST_POLICY.json`, the manifest generator, the verifier, any included proof input, any certifier, or any replay evidence require regeneration of `SHA256SUMS` and successful verification before merge.

Documentation-only and GitHub-automation-only changes do not require manifest regeneration unless they also modify a path included by the policy.

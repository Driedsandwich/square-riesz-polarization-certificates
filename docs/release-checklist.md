# GitHub release operator record — v1.0.0

This file records the completed v1.0.0 publication process. The canonical state is the public repository, final tag, and GitHub Release.

## Completed source and validation checks

- [x] Repository metadata finalized for `Driedsandwich/square-riesz-polarization-certificates`.
- [x] `python scripts/verify_manifest.py` passed.
- [x] `python scripts/check_release.py` passed.
- [x] The included clean-room replay records 88/88 `CERTIFIED`.
- [x] The publication audit reported zero secret/privacy findings before release.

## Completed GitHub publication checks

- [x] Complete finalized tree pushed to `main`.
- [x] Tag `v1.0.0` created from final `main`.
- [x] GitHub Release created from `RELEASE_NOTES_v1.0.0.md`.
- [x] Canonical ZIP and `.sha256` companion attached.
- [x] Asset names, sizes, and SHA-256 verified after re-downloading from the Release.
- [x] Repository changed to public visibility.
- [x] README, licenses, citation metadata, and workflows are publicly readable.
- [ ] A post-publication `smoke-test` run on final `main` has been independently recorded in this document.

## Explicitly out of scope

- Zenodo/DOI registration.
- Emailing Erich Friedman or any third party.
- Publishing private correspondence, screenshots, internal master archives, or unrelated files.

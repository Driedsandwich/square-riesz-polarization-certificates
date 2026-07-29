# GitHub release operator checklist — v1.0.0

This is an execution checklist, not a historical status record. The canonical publication state is the GitHub repository, tag, and Release themselves.

## Source and validation

- [ ] Finalize repository metadata with the authenticated GitHub owner and repository URL.
- [ ] Run `python scripts/verify_manifest.py`.
- [ ] Run `python scripts/check_release.py`.
- [ ] Run `python scripts/verify_all.py --quick --jobs 2`.
- [ ] Confirm the included full clean-room replay remains `88/88 CERTIFIED`.
- [ ] Confirm publication audit reports zero findings.

## GitHub publication

- [ ] Create or confirm the repository `square-riesz-polarization-certificates` in the authenticated personal namespace.
- [ ] Push the complete finalized tree to the `main` branch.
- [ ] Verify the `smoke-test` GitHub Actions workflow passes.
- [ ] Create tag `v1.0.0` from the final `main` commit.
- [ ] Create the GitHub Release using `RELEASE_NOTES_v1.0.0.md` plus the prepared release body.
- [ ] Attach the deterministic release ZIP and its `.sha256` file.
- [ ] Verify asset names, asset sizes, and the published SHA-256.
- [ ] Verify the repository is public and the README, licenses, citation metadata, and workflows are visible.

## Explicitly out of scope for this publication action

- Zenodo/DOI registration.
- Emailing Erich Friedman or any third party.
- Deleting an existing repository or overwriting a repository-name collision.
- Publishing private correspondence, screenshots, internal master archives, or unrelated files.

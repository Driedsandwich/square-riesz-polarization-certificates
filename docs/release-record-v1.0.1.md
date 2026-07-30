# GitHub release operator record — v1.0.1

## Mathematical boundary

- Fixed configurations changed from v1.0.0: **no**
- Certified lower bounds changed from v1.0.0: **no**
- Exact certifier algorithms changed from v1.0.0: **no**
- Fresh publication replay: **88/88 CERTIFIED**

## Completed pre-publication checks

- [x] Scoped manifest regenerated and verified.
- [x] Release structure check passed.
- [x] All 88 exact certifiers passed in fresh processes.
- [x] Privacy and secret scan reported zero findings.
- [x] README public-attribution boundary preserved.
- [x] v1.0.0 tag, Release, and existing assets were not modified.

## Publication mechanism

The canonical deterministic ZIP is generated from the final tagged commit. A draft Release receives the ZIP and checksum companion before publication. After draft-asset verification, the Release is published and checked for immutable status.

Workflow run: https://github.com/Driedsandwich/square-riesz-polarization-certificates/actions/runs/30508499207

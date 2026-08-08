# Publication status

## Which Release is canonical

**This file does not attest to its own publication.** It is part of the release
tree, so it cannot know whether the Release that carries it exists. The live
authority is GitHub:

- Intended version and tag: `v1.0.2`
- Intended Release: https://github.com/Driedsandwich/square-riesz-polarization-certificates/releases/tag/v1.0.2

The rule, which holds both before and after that Release is created:

> If GitHub reports the `v1.0.2` Release as published and immutable, then
> `v1.0.2` is the latest canonical Release. Otherwise `v1.0.1` remains the
> latest canonical Release.

Resolve it against the GitHub Release page or API, not against this file.

- Intended release assets — two canonical distribution assets and one auxiliary
  publication-integrity asset:
  - `square-riesz-polarization-certificates-v1.0.2.zip`
  - `square-riesz-polarization-certificates-v1.0.2.zip.sha256`
  - `square-riesz-polarization-certificates-v1.0.2.publication-attestation.json`
- Authority for the final asset digests and sizes: the publication-attestation
  asset and GitHub's own Release asset metadata, confirmed by downloading the
  assets. They are deliberately not recorded in this file, because a file inside
  the release tree cannot state the digest of an archive built from the commit
  that contains it.
- The release title and notes are **not** authoritative. GitHub's immutable
  releases protect the tag and the assets; its documentation states that once
  immutable releases are enabled, only the title and release notes can be edited
  after publication. Integrity records therefore live in an asset, and GitHub's
  generated Release attestation binds the tag, the commit and all three assets.
- The `v1.0.0` and `v1.0.1` tags, Releases and assets are unchanged by
  `v1.0.2`.

The corrections carried by `v1.0.2` are implemented on `main` at merge commit
`2adfffb7dc68f40ea52fd1ed78bc2f11a46de78b`; `docs/errata-v1.0.1.md` describes
them.

## The v1.0.1 Release

- Canonical repository: https://github.com/Driedsandwich/square-riesz-polarization-certificates
- Release: https://github.com/Driedsandwich/square-riesz-polarization-certificates/releases/tag/v1.0.1
- Release tag: `v1.0.1`
- GitHub Release publication date (UTC): 2026-07-30
- Canonical manually uploaded ZIP: `square-riesz-polarization-certificates-v1.0.1.zip`
- Canonical checksum asset: `square-riesz-polarization-certificates-v1.0.1.zip.sha256`

The accompanying `.sha256` asset records the canonical ZIP SHA-256. The Release publication process verifies the tag target, downloads both assets again, and checks the ZIP against that checksum before declaring completion.

`v1.0.1` is a documentation, provenance, reproducibility, integrity-policy, and repository-operations patch. It does not change the fixed configurations, certified lower bounds, exact certifiers, or preserved mathematical replay results from `v1.0.0`.

## Preserved v1.0.0 snapshot

- Release: https://github.com/Driedsandwich/square-riesz-polarization-certificates/releases/tag/v1.0.0
- Tag target: `2f01c00693a1304b063077238d4e86ba7fae9744`
- Publication date (UTC): 2026-07-29
- Canonical ZIP: `square-riesz-polarization-certificates-v1.0.0.zip`
- Canonical ZIP size: 610,729 bytes
- Canonical ZIP SHA-256: `3efed92c6227594f04374b6b3d795c1c8f5d0fc6942734678559e93c9220351b`

The `v1.0.0` tag, Release, and two existing assets remain unchanged.

## Asset interpretation

The manually uploaded ZIP and its `.sha256` companion are the canonical Release assets. GitHub's automatically generated “Source code” archives are convenience downloads and are not the canonical deterministic ZIP.

The mathematical certificate evidence is independent of the hosting URLs above. This project is independent and is not affiliated with or endorsed by Erich Friedman or OpenAI.

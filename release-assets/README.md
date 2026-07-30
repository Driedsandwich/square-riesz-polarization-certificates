# Release assets

## v1.0.1

The GitHub `v1.0.1` Release contains exactly two manually uploaded canonical assets:

- `square-riesz-polarization-certificates-v1.0.1.zip`
- `square-riesz-polarization-certificates-v1.0.1.zip.sha256`

The checksum companion records the canonical ZIP SHA-256. The Release operator generates the deterministic ZIP from the final tagged commit, verifies an extracted copy, uploads both assets to a draft Release, publishes the Release, downloads both assets again, and checks the ZIP against the checksum.

## Preserved v1.0.0 assets

The original `v1.0.0` Release remains unchanged:

- `square-riesz-polarization-certificates-v1.0.0.zip`
- `square-riesz-polarization-certificates-v1.0.0.zip.sha256`

```text
size: 610,729 bytes
SHA-256: 3efed92c6227594f04374b6b3d795c1c8f5d0fc6942734678559e93c9220351b
```

## Interpretation

Canonical ZIPs are generated outside the repository tree to avoid recursive packaging. GitHub's automatically generated “Source code” archives are convenience downloads and are not the canonical deterministic Release assets.

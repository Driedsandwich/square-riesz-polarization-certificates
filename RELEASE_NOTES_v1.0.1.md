# v1.0.1 release notes

## Patch-release boundary

This patch release does **not** change any fixed configuration, certified lower bound, exact certifier algorithm, or mathematical replay result from `v1.0.0`.

The mathematical corpus remains:

- 44 certified fixed configurations for `n=7,8,10,11,12` and `14..52`;
- 88 exact-rational certifiers, two per configuration;
- 88/88 certified in the preserved clean-room replay evidence.

## Documentation and provenance corrections

- Clarifies that the repository verifies certificates but does not reproduce the original exploratory search process.
- Clarifies that published all-local-minimum information consists of numerical counts where available, not complete coordinate lists and not proof inputs.
- Identifies Erich Friedman's “Maximizing Minimum Light Intensity” page as the primary problem source and distinguishes this independent certificate corpus from the original numerical record board.
- Distinguishes the `n=36` external-submission stopping point from the current independently audited public-corpus endpoint at `n=52`; `n=52` is not a mathematical cutoff.
- Preserves the README's public attribution under the GitHub handle rather than displaying a real name.

## Reproducibility and integrity

- Adds methodology, references, security guidance, and contribution templates.
- Introduces `MANIFEST_POLICY.json` and a deterministic 545-file `SHA256SUMS` covering the exact certificate and reproducibility corpus.
- Adds completeness checks for missing, unexpected, duplicate, unsafe, malformed, and hash-mismatched manifest entries.
- Protects the complete published snapshot, including documentation and GitHub automation, with the canonical Release ZIP SHA-256 and its companion checksum asset.
- Re-runs all 88 exact certifiers during release publication before the tag and assets are created.

## Repository operations

- Adds Dependabot configuration and issue/PR templates.
- Uses least-privilege permanent workflows.
- Updates `actions/checkout` and `actions/setup-python` to v7 after successful manifest, release-structure, and quick-verifier checks.

## Claim boundary

The release certifies lower bounds for the exact supplied finite-decimal configurations. It does not establish global optimality, exhaustive novelty, or official record-board status.

## Canonical assets

Use the two manually uploaded assets:

- `square-riesz-polarization-certificates-v1.0.1.zip`
- `square-riesz-polarization-certificates-v1.0.1.zip.sha256`

GitHub's automatically generated “Source code” archives are convenience downloads and are not the canonical deterministic Release ZIP.

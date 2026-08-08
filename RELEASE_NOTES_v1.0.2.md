# v1.0.2 release notes

A corrective patch release. It repairs published decimal values that were not
valid upper bounds, clarifies two pieces of descriptive prose, and strengthens
the verification and integrity checking around the corpus.

## Corrective patch boundary

This release changes published decimals and repository tooling.

It does not change the fixed configurations, certified lower bounds, upper
witness points, certifier sources, branch-and-bound method, or Taylor bounds. It
corrects decimal presentations of upper witness enclosures, the interval widths
derived from them, and related descriptive prose.

Only two kinds of value are arithmetically corrected: `rigorous_upper_witness`
and the `interval_width` derived from it. Nothing else in the result tables is
touched.

## Upper-witness decimal corrections

The published `rigorous_upper_witness` decimals had been rounded to nearest.
Rounding a value that is meant to be an upper bound to nearest can move it
*below* the quantity it is supposed to bound, and that is what had happened:
for eighteen of the forty-four configurations the published decimal was smaller
than the exact potential at that configuration's own upper witness point, so it
was not an upper bound at all.

Those decimals are now rounded outward. Each correction is `+1` in the final
published digit — the smallest possible change that restores the bound. The
`interval_width` of the same rows follows from the corrected value and is
recomputed accordingly.

The affected configurations are:

```text
n=8   n=15  n=18  n=19  n=20  n=24
n=26  n=27  n=29  n=30  n=32  n=35
n=36  n=39  n=43  n=45  n=46  n=47
```

The remaining twenty-six published decimals were already at or above the exact
witness potential and are unchanged. They came from the same round-to-nearest
pipeline; in those rows the nearest-rounded result happened to lie above the
exact value. They were not produced by an outward-rounding procedure.

## Provenance wording corrections

The descriptive `symmetry_or_family` field of two configurations claimed exact
symmetries that the published finite decimals do not have. That field is
non-normative provenance prose; no bound depends on it, and no number changes
as a result of this correction. The exact invariance of every configuration
under the eight symmetries of the square is now computable directly with
`certificate_lib.exact_square_symmetries`.

`docs/errata-v1.0.1.md` keeps this clarification separate from the arithmetic
correction above, because they are defects of different kinds.

## Verification and integrity hardening

- A frozen corpus of 531 files, pinned to the objects of the `v1.0.1` release
  commit, is checked before anything else in both workflows. Inside a Git
  repository the authority is the release commit itself, read raw, with object
  replacement disabled on every read.
- One shared proof-output contract now governs live runs, the replay validator,
  the stored historical evidence and saved replays. A status-only or
  structurally incomplete stdout no longer qualifies as a successful run. A
  source-level proof-skipping rewrite that emits internally consistent fake
  measurements is prevented by the frozen-corpus Git-object anchor below; the
  output contract alone does not prove that `certify()` performed valid
  mathematics.
- The certifier entry-point check is structural rather than a count of calls.
- The result tables are build products of a single deterministic generator.
- Every upper witness point is checked to lie in the unit square.
- Replay output is re-derived from its own files, including per-record script
  digests and recomputed aggregates.

`CHANGELOG.md` carries the itemised list.

## Mathematical and claim boundary

Unchanged from `v1.0.1`:

- the certified lower bounds of all forty-four configurations;
- the fixed configuration coordinates, which remain exact finite decimals;
- the upper witness points;
- the exact certifier sources, all eighty-eight of them;
- the branch-and-bound method and the Taylor bounds it uses;
- the preserved historical replay evidence.

What this release establishes is what its certificates establish: for each
fixed configuration, a certified lower bound on the minimum potential over the
unit square, together with an upper witness value at a stated point. It does
not claim global optimality of any configuration, it is not an official record
of the underlying problem, and it makes no claim of exhaustive novelty.

Before publication, all eighty-eight exact certifiers are replayed in fresh
processes and the resulting artifact is independently validated. That full
replay is a precondition of the release, not a post-hoc check.

## Canonical assets

This release carries three assets: two canonical distribution assets and one
auxiliary publication-integrity asset.

```text
square-riesz-polarization-certificates-v1.0.2.zip                             distribution
square-riesz-polarization-certificates-v1.0.2.zip.sha256                      distribution
square-riesz-polarization-certificates-v1.0.2.publication-attestation.json    publication integrity
```

The `.sha256` companion records the canonical ZIP digest. GitHub's
automatically generated "Source code" archives are convenience downloads and
are not the canonical deterministic release assets.

The ZIP is produced by `scripts/build_release_assets.py` from the exact tag
target. The attestation asset is produced by
`scripts/build_publication_attestation.py` from facts measured during the
release, and is uploaded to the draft Release before publication.

**Which builder counts.** A release build is valid only when the script that
executes is byte-identical to `scripts/build_release_assets.py` inside the exact
commit being archived. The builder reads that blob out of the target tree,
hashes it and hashes the file it is itself running from, and refuses before
producing anything if the two differ. Recording a blob id and a file digest is
not the same as requiring them to describe the same bytes.

**The digest is agreed before the tag exists.** A `v*` tag cannot be moved once
it is created, so the final tagged build is required to reproduce a digest
measured by an earlier build of the same commit made without the tag. A tagged
build with no expected digest is refused.

**The build record travels with the attestation.** The machine-written
`build-record.json` is embedded whole in the attestation asset, and the
`build_record_sha256` published alongside it is recomputable from that embedded
object. A reader of the Release can therefore check the digest against its
preimage without access to the build machine.

**Delivery states.** Both generators distinguish a refusal from a durability
question. Exit `2` means the tool stopped before its publication commit point
and no output exists. Exit `3` means the output exists but its durability has
not been confirmed; it is not a failure to publish, and it is not something to
retry automatically. Exit `3` holds even when the check that would describe the
output also fails — in that case the tool says the output exists and that its
completeness could not be verified, which is a weaker claim than "incomplete"
and a different claim from "absent". Once the tag exists, a defect in the
content or the digest is repaired by a new patch version, never by moving the
tag.

**The draft's contents are counted, not assumed.** Before the attestation is
generated the draft Release must carry exactly the two distribution assets, and
after the attestation is uploaded exactly those two plus the attestation. The
first inventory is an input the generator checks; the second cannot be, because
a file cannot describe its own upload, so it is carried by the external
execution evidence and by GitHub's generated Release attestation.

**Where the commit point actually is.** `os.rename` and `os.replace` finish
inside the C call, and an interruption can arrive before the next Python
statement records that they did. Wrapping the call alone is not enough: the
statement after the guard, and the success report after the helper returns, are
both after the output exists. The transaction therefore runs from the syscall to
the command's return, and the outcome is decided by inspecting the filesystem
rather than by a flag that may never have been set: only a definite absence is
reported as an absence, and an inspection that cannot answer is treated as
published.

**What is not claimed.** These tools are not interruption-proof. `SIGKILL`, a
process crash and a loss of power cannot be caught by any handler, and no code
here pretends otherwise. What is bounded is the *reporting*: no path prints
that nothing was published when something may have been.

**Where the digests live.** The distribution asset digests and sizes are
recorded in the publication-attestation asset and in GitHub's own Release asset
metadata, which you can confirm by downloading the assets. They are not
recorded in `PUBLICATION_STATUS.md`, and not in these notes: an archive's digest
cannot be stated by a file inside that archive.

**What is authoritative, and what is not.** GitHub's generated Release
attestation binds the tag, the release commit and all three assets, and the
release assets are what immutability protects. The release title and these notes
remain editable after publication, so they are human-readable description and
carry no integrity authority.

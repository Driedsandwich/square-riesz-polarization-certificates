# The frozen mathematical corpus

## What is frozen

531 files carry the mathematics of this repository:

| Root | Files | What it holds |
| --- | ---: | --- |
| `certifiers/` | 88 | the two exact branch-and-bound certifiers of each configuration |
| `data/configurations/` | 88 | the published coordinates, and their provenance files |
| `evidence/full-cleanroom-replay/` | 267 | the historical clean-room replay: logs, per-job metadata, summaries |
| `evidence/saved-replays/` | 88 | the per-certifier stdout snapshots |

They are fixed by the published release:

```
BASE_VERSION = v1.0.1
BASE_COMMIT  = d92992101ca45a5cd755b8d962652ab7e4329973
```

`scripts/check_frozen_corpus.py` enforces that. `data/frozen-corpus-v1.0.1.sha256`
lists the 531 paths with their SHA-256 values.

## Where the authority actually lives

The baseline file is **not** an immutable anchor, and this document previously
said otherwise. It travels with the repository: it is in every clone, every
pull request, every evidence bundle, and anyone who can edit a certifier can
edit it in the same change.

That was measured, not argued. A certifier rewritten to skip its proof, with
the historical script hash, the per-job metadata, the aggregate CSV and JSON,
this baseline and `SHA256SUMS` all updated in one change, produced
`status: CERTIFIED`, `splits: 0`, `leaf_count: 1` and exit 0 from
`verify_one.py`, while `check_frozen_corpus.py`, `verify_manifest.py`,
`check_release.py`, `check_semantic_consistency.py`,
`regenerate_certified_results.py --check` and `audit_upper_witness.py` all
reported success. Editing the header to name a different base commit was also
accepted, because nothing compared that name to anything.

So the accurate statement of what each layer is:

| Layer | What it is | What it is not |
| --- | --- | --- |
| `SHA256SUMS` | the repository is internally consistent right now | evidence that the corpus is unchanged; it is regenerated with every change |
| `data/frozen-corpus-v1.0.1.sha256` | a readable mirror of the release blobs, not written by any ordinary command | an immutable anchor; it is a file in the repository and can be edited alongside the corpus |
| the raw `v1.0.1` commit object | the authority inside a Git repository: its bytes cannot be rewritten without changing the commit id — **provided it is read with object replacement disabled** | available in an archive that has no `.git` |
| the release ZIP digest | the authority for a distributed archive | present inside the archive |

Naming the commit is necessary but not sufficient on its own. `git replace`
lets a repository serve different bytes under an unchanged object name: with a
commit or blob replacement configured, `git ls-tree` and `git cat-file` return
the substituted content, and a checker that follows them reports
`git_anchor=verified` on a corpus that has been altered. Both halves of that
were measured, with `git replace <commit> <commit>` and with
`git replace <blob> <blob>`.

So every Git read here disables replacement — `git --no-replace-objects`,
`GIT_NO_REPLACE_OBJECTS=1`, and `GIT_REPLACE_REF_BASE` dropped from the
environment so neither the caller nor a repository-local setting can redirect
it — and every `git cat-file --batch` response is checked against the object
id, type and size that were requested, with the record separator and the end of
the stream verified so a reordered, missing, extra or truncated response cannot
be read past. `refs/replace/` is enumerated and reported; under
`--require-git-anchor` its mere existence is a failure, because someone
arranging for these objects to be served as something else is worth stopping
for even though the reads ignore it.

Inside a Git repository the check then reads the frozen file set and its
contents straight out of `BASE_COMMIT` and requires three things to agree:
**the raw release blobs, the in-tree baseline, and the working tree.** Editing
the baseline to match an edited tree fails, because the release objects still
disagree with both.

Outside a Git repository — a release archive, an evidence snapshot — there are
no objects to read. The baseline check still runs, and the run reports
`git_anchor=unverifiable` and `git_anchor_unverifiable=1` instead of implying a
comparison it did not make. `--require-git-anchor` turns that state into a
failure, and a `git` command that errors is never treated as "no Git".

## Bytes are not the whole file

Two files with the same digest are not necessarily the same file. A frozen path
replaced by a symbolic link to an identical copy reads through
`Path.is_file()` as present and unchanged, and so does one that has gained the
executable bit. Both were measured against the previous implementation and both
passed.

The working tree is therefore inventoried with `lstat` and nothing is followed:
each of the four roots must be a real directory rather than a link, every path
must be a regular file, and a symlink, FIFO, socket or device is reported by
name instead of being read through or silently dropped. When the release
objects are available, the Git file mode is compared too — `100644` against
`100755` — so the executable bit is anchored along with the content. All 531
paths of `v1.0.1` are `100644`; none is executable.

File modes are POSIX. On a platform without those permission bits the mode
comparison cannot be made, and the run reports `mode_anchor_unverifiable=1`
rather than passing quietly; CI (Ubuntu) and local development (macOS) both
perform it. In a snapshot with no `.git` there is no release mode to compare
against, so the same flag is set, but the regular-file and no-symlink
requirements still hold.

## What the check rejects

- a changed byte in any of the 531 files, whether or not the baseline follows
- a file mode that differs from the release, with the bytes unchanged
- a frozen path that is a symlink, a FIFO, a socket or a device
- a frozen root that is a symlink rather than a directory
- object replacement configured in the repository, under `--require-git-anchor`
- a `cat-file --batch` response that is not the object, type or size requested
- a missing file, an unlisted file under a frozen root, or a moved path
  (reported as a move when the digest is unchanged)
- a baseline header that does not name `v1.0.1` and `BASE_COMMIT` exactly, that
  repeats one of `base-version`, `base-commit` or `file-count`, that omits one of
  them, or that spells one of them malformed
- a baseline whose entries disagree with the release blobs, even when they
  agree with the working tree
- a duplicated path, an unsafe path, a malformed digest, or a `file-count` that
  does not match the entries
- a `v1.0.1` tag that does not point at `BASE_COMMIT`
- `--require-git-anchor` when the objects cannot be read

## How to run it

```bash
python scripts/check_frozen_corpus.py

python scripts/check_frozen_corpus.py \
  --expect-base-version v1.0.1 \
  --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 \
  --require-git-anchor
```

Both workflows run the second form as their first step, with
`fetch-depth: 0` so the release commit and tag are present in the checkout.

Exit codes: `0` agreement, `1` a difference was found, `2` the check could not
be performed as demanded — an unusable baseline, or a required anchor that
could not be read.

## The baseline file format

```
# <free prose, any number of lines>
# base-version: <tag name>
# base-commit: <40 lowercase hex characters>
# file-count: <decimal count of entries>
<sha256>  <repository-relative path>
...
```

`base-version`, `base-commit` and `file-count` are *structured headers*: each
must appear exactly once, and a repeated one is an error rather than a
last-one-wins overwrite — `# base-version: v9.9.9` above the real line was
previously accepted in silence. Any other `# name: value` line is prose and may
repeat. Entries are `<sha256>  <path>` with two spaces, sorted by path, no
duplicates, and every path under one of the four frozen roots. The file lists
digests only; file modes are anchored against the release objects, not here.

GNU `sha256sum -c` verifies the entries and prints a "lines are improperly
formatted" warning for the comment block. `scripts/check_frozen_corpus.py` is
the authoritative reader.

## Changing the corpus

Editing a certifier, a configuration or the historical evidence is a research
release, not a maintenance patch. When that happens:

1. make the mathematical change and replay it;
2. generate a new baseline from the new release commit, under a new file name
   carrying that version, for example `data/frozen-corpus-v1.1.0.sha256`;
3. update `BASE_VERSION` and `BASE_COMMIT` in `scripts/check_frozen_corpus.py`
   and the workflow invocations;
4. say so in `CHANGELOG.md`, naming what changed and why.

There is deliberately no `--write` mode. Regenerating the baseline is not a step
in any maintenance or CI flow, and `scripts/regenerate_manifest.py` does not
write this file: if it did, a corpus edit would refresh its own baseline and the
check would report success on exactly the change it exists to catch. Since the
release objects are now the authority, refreshing the baseline alone would fail
anyway — but the point of keeping it out of the automated path is that nothing
should make that mistake convenient.

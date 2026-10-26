# CLAUDE.md

このリポジトリで作業する AI のための決まりです。ここに書いた手順は、コミット `b57c436`（ブランチ `audit/v1.0.2-upper-witness-hardening`）の上で実際に実行して確かめたものです。全体像は `docs/ARCHITECTURE.md`、用語は `docs/GLOSSARY.md` を読んでください。

## このリポジトリは何か

単位正方形に置いた決まった点光源の配置について、「一番暗い場所の明るさはこの値以上」を分数計算で証明するプログラム集です。証明プログラムは 44 配置 × 2 方式 = 88 本。証明するのは固定した配置の下限だけで、大域最適性ではありません（`README.md:44-50`、`docs/claim-boundaries.md`）。文書やコミットでも、それ以上のことを主張しないでください。

## 準備

- Python 3.13 と標準ライブラリだけで動きます。外部ライブラリのインストールは不要です（`requirements-analysis.txt` の `numpy` / `scipy` は証明には使われません）。
- **タグと全履歴が必要です。** 浅い複製やタグの無い複製では、`check_frozen_corpus.py --require-git-anchor` と単体テスト 1 件（`test_round5_hardening.FrozenCorpusIsAnchoredToTheRelease.test_release_digests_are_read_from_the_objects`）が失敗します。最初に取ってきてください:

```bash
git fetch origin tag v1.0.0 tag v1.0.1
```

## テストと検査（この順で、リポジトリ直下から）

すべて `-B` を付けます。`__pycache__` ができると `scripts/check_release.py` が失敗します。

```bash
python -B -m unittest discover -s tests
python -B scripts/check_frozen_corpus.py \
  --expect-base-version v1.0.1 \
  --expect-base-commit d92992101ca45a5cd755b8d962652ab7e4329973 \
  --require-git-anchor
python -B scripts/verify_manifest.py
python -B scripts/check_release.py
python -B scripts/check_semantic_consistency.py
python -B scripts/regenerate_certified_results.py --check
python -B scripts/audit_upper_witness.py
python -B scripts/verify_one.py --n 15 --method both
python -B scripts/verify_all.py --quick --jobs 2
```

確かめた結果と時間（4 コアの環境）:

| コマンド | 通ったときの出力 | 時間 |
| --- | --- | --- |
| `unittest discover -s tests` | `Ran 220 tests ... OK` | 約 3 分半 |
| `check_frozen_corpus.py ...` | `531 files agree ...` | 数秒 |
| `verify_manifest.py` | `expected=564 listed=564 missing=0 unexpected=0 bad_hash=0 errors=0` | 数秒 |
| `check_release.py` | `issues=0` | 数秒 |
| `check_semantic_consistency.py` | `problems=0` | 数秒 |
| `regenerate_certified_results.py --check` | `records=44 differences=0` | 数秒 |
| `audit_upper_witness.py` | `below_exact=0` | 数秒 |
| `verify_one.py --n 15 --method both` | `certified=2/2` | 約 40 秒 |
| `verify_all.py --quick --jobs 2` | `verifier_count=10 certified_count=10 failed_count=0` | 約 2 分 |

88 本すべての実行（重いので必要なときだけ）:

```bash
python -B scripts/verify_all.py --all --jobs 4 --output-dir <まだ無いフォルダ>
python -B scripts/validate_replay_output.py <同じフォルダ> --expect-all
```

- 4 並列で約 6 分。結果は `verifier_count=88 certified_count=88 failed_count=0` と `problems=0`。
- `--output-dir` は存在しないか空のフォルダでなければ拒否されます。リポジトリの外（一時フォルダ）に出すか、`.gitignore` 済みの `replay-output/` を使ってください。
- `validate_replay_output.py` は記録された `source_git_commit` を現在の `HEAD` と比べます。実行と検証の間にコミットしないでください。

注意:

- テストは `python -B -m unittest discover -s tests` の形で実行してください。`python -m unittest tests.test_round5_hardening` のようなモジュール指定はエラーになりました（`tests/support.py` を同じフォルダから読み込む作りのため）。1 ファイルだけ動かすときは `python -B -m unittest discover -s tests -p 'test_round5_hardening.py'`。
- `python -O` や `PYTHONOPTIMIZE` は使わないでください。証明プログラムの最後の `assert` が消えるため、実行スクリプトは起動を拒否します（`scripts/verifier_runner.py:90-98`）。
- 終わったら `git status --short` で、`__pycache__` や実行結果のフォルダが残っていないことを確かめてください。

## 触ってはいけない物

| 対象 | 理由 |
| --- | --- |
| `certifiers/`（88 本） | 凍結された数学の本体。v1.0.1 の Git の中身と 1 バイト単位・権限単位で比べられる（`scripts/check_frozen_corpus.py:82-87`） |
| `data/configurations/` | 同上（座標） |
| `evidence/full-cleanroom-replay/`, `evidence/saved-replays/` | 同上（過去の実行記録）。新しい実行結果をここに書き込まない |
| `data/frozen-corpus-v1.0.1.sha256` | 凍結部分の指紋一覧。研究としての新しいリリース以外では変えない（同ファイル冒頭のコメント） |
| タグ `v1.0.0`, `v1.0.1` と、公開済みのリリースと添付ファイル | 公開済みの版そのもの |
| `VERSION`, `MANIFEST_POLICY.json`, `LICENSE`, `LICENSE-CODE`, `LICENSE-DATA-DOCS.md` | 版番号と指紋の範囲とライセンス。依頼が無い限り変えない |
| `data/certified-results.csv`, `data/certified-results.json` | 生成物。手で編集しない。変えるときは `python -B scripts/regenerate_certified_results.py --write` だけを使う（CSV は CRLF 改行） |
| `.gitattributes` の `* -text` | 改行コードの変換を止めて指紋を守っている（`.gitattributes:1-17`） |

`scripts/`, `tests/`, `data/` は `SHA256SUMS` の範囲内です（`MANIFEST_POLICY.json`）。これらを変えたら `python -B scripts/regenerate_manifest.py` で作り直し、`verify_manifest.py` で確かめてください。`docs/`, `.github/`, `README.md` などの文書や、この `CLAUDE.md` は範囲外で、変えても作り直しは要りません。これは `docs/ARCHITECTURE.md`・`docs/GLOSSARY.md`・この `CLAUDE.md` を追加したあとに `verify_manifest.py`（`unexpected=0`）、`check_release.py`、`check_semantic_consistency.py` を実行して確かめました。

## 公開物としての注意

このリポジトリは公開されています。

- 個人の名前・メールアドレス・手元の絶対パス（`/home/...`, `/Users/...` など）・鍵・トークン・認証情報を、ファイルにもコミットメッセージにも書かないでください。パスは常にリポジトリ直下からの相対パスで書きます。
- 既存のライセンスや帰属表示のファイル（`LICENSE` など）に書かれた名前は意図して載せているものです。それを他のファイルに書き写したり、増やしたりしないでください。
- 記録ページの画像・HTML・私信は入れません（`CONTRIBUTING.md`、`NOTICE.md`）。
- 見つけた秘密情報は、値を書かずに種類と場所だけを報告してください。

## 変更の流儀

- 頼まれたことだけを、最小の差分で行います。依頼にないコードの整理や書式の変更を混ぜないでください。
- 文書（`docs/`）は既存の書き方に合わせます: `#` の見出し、`|` の表、コードは囲みブロック、パスやコマンドは `` ` `` で囲む、先頭の設定ブロック（front matter）は付けない。
- 実際に読んだ・実行した事実と、推測を分けて書きます。読んでいない部分は「未確認」と書きます。
- 下限を大域最適性や公式記録のように書かないでください（`CONTRIBUTING.md`）。
- 変更のあとは、上の「テストと検査」のうち速いもの（単体テストから `audit_upper_witness.py` まで）を実行してから commit してください。
- `CHANGELOG.md` には、依頼された変更だけを書きます。

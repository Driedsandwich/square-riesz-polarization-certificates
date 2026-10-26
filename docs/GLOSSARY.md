# Glossary

このリポジトリのコードや文書に出てくる言葉を、やさしい言葉で説明する用語集です。全体の流れは `docs/ARCHITECTURE.md` にあります。

- 各用語の「根拠」は、その言葉が実際に使われている、または定義されているファイルとおおよその行です（`ファイル:行`）。
- 中身を読んで確かめていない部分は **未確認** と書いています。

## 1. 問題そのものに関する言葉

| 用語 | やさしい説明 | 根拠 |
| --- | --- | --- |
| 単位正方形 `[0,1]^2` | 縦横 1 の正方形。光源を置く場所であり、明るさの最小を探す範囲でもある | `README.md:7` |
| 光源 (light, source) | 正方形の中に置く点。コードでは `LIGHTS` という一覧に座標が並ぶ | `certifiers/n15/spectral.py:49-65` |
| 明るさ・ポテンシャル (potential, intensity) | ある点での明るさ。各光源からの距離の 2 乗の逆数を全部足したもの。光源に近いほど大きい | `README.md:9-11`、`certifiers/n15/spectral.py:86-94` |
| 最小の明るさ `I(X)` | 正方形の中で一番暗い場所の明るさ | `README.md:15-17` |
| 配置 (configuration) | `n` 個の光源の座標の組。このリポジトリでは小数で書かれた決まった座標 | `data/configurations/n15/coordinates.csv` |
| Riesz 2-polarization（リース分極） | この問題の数学での呼び名。距離の 2 乗で弱まる場合（`s=2`）にあたる | `docs/references.md`、`CITATION.cff` |
| 記録ページ (record board) | 問題を出した人が管理する、これまでで一番良い数値の一覧ページ。このリポジトリとは別物 | `README.md:101-109`、`docs/external-status.md` |
| 大域最適 (global optimality) | 「どんな置き方よりもこれが一番良い」ということ。このリポジトリは **これを証明していない** | `README.md:50`、`docs/claim-boundaries.md` |

## 2. 証明の仕組みに関する言葉

| 用語 | やさしい説明 | 根拠 |
| --- | --- | --- |
| 証明プログラム (certifier, verifier) | 1 つの配置について「一番暗い場所でもこの値以上」を計算で確かめるプログラム。`n` ごとに 2 本ある | `certifiers/n15/spectral.py:1-32` |
| 下限 (lower bound) | 「少なくともこれ以上」という値。このリポジトリが証明するのはこれ | `README.md:46-48` |
| `TARGET`（目標値） | 証明しようとしている下限の値。証明プログラムの先頭近くに分数で書かれている | `certifiers/n15/spectral.py:44` |
| 有理数演算・分数計算 (`Fraction`, `Q`) | 小数ではなく分数のまま計算すること。丸め誤差が一切入らないので、計算結果をそのまま証明に使える | `certifiers/n15/spectral.py:37`、`certifiers/n15/componentwise.py:6-7` |
| 分枝限定法 (branch-and-bound) | 正方形を箱に分け、「この箱は大丈夫」と言えた箱は済みにし、言えない箱だけをさらに半分に切っていく方法。箱が無くなれば正方形全体で証明できたことになる | `certifiers/n15/spectral.py:28-29`, `:152-207` |
| 箱 (box) | 調べる範囲の小さな長方形。`(x0, x1, y0, y1)` の 4 つの数で表す | `certifiers/n15/spectral.py:47` |
| 分割回数 (`splits`) | 箱を半分に切った回数 | `certifiers/n15/spectral.py:197`, `:226` |
| 葉 (`leaf_count`) | 最後まで残った「済み」の箱の数 | `certifiers/n15/spectral.py:166-173`, `:227` |
| 深さ (`maximum_depth`) | 一番細かく切った箱が何回切られたものか | `certifiers/n15/spectral.py:168`, `:228` |
| 最小の葉の下限 (`minimum_leaf_lower_bound`) | 済みになった箱の下限のうち一番小さいもの。これが `TARGET` 以上なら証明成立 | `certifiers/n15/spectral.py:169-172`, `:245` |
| テイラー展開による下限 | 箱の中心での値と傾きから、箱の中の値を見積もる方法。曲がり具合（2 次の誤差）を差し引いて安全側にする | `certifiers/n15/spectral.py:20-26`, `:133-138` |
| ヘッセ行列 (Hessian) | 曲がり具合を表す 2×2 の表。成分は `H_xx`, `H_yy`, `H_xy` | `certifiers/n15/componentwise.py:86-109` |
| スペクトル法 (spectral) | 曲がり具合を、ヘッセ行列の一番小さい固有値の下限でまとめて見積もるやり方。`spectral.py` | `certifiers/n15/spectral.py:20-26` |
| 成分ごと法 (componentwise) | 曲がり具合を、ヘッセ行列の 3 つの成分それぞれの範囲（区間）で見積もるやり方。`componentwise.py` | `certifiers/n15/componentwise.py:9-11`, `:112-123` |
| 区間 (interval) | 「この値はここからここまでの間にある」という範囲。下端と上端の 2 つの数 | `certifiers/n15/componentwise.py:46-62` |
| 対称性による削減 | 配置が左右・上下に対称であることを `assert` で厳密に確かめ、正方形の 4 分の 1 だけを調べる工夫。`n=17` 以降の証明プログラムで使われる | `certifiers/n40/spectral.py:14`, `:95-97`, `:183` |
| 上側証人点 (upper witness point) | 正方形の中から選んだ 1 点。そこでの明るさは「最小値はこれ以下」という上限になる。コードでは `UPPER_WITNESS`・`WITNESS_POINT`・`WITNESS` という名前か、`main()` の中で `(0, 0)` を直接使う | `scripts/certificate_lib.py:562`、`certifiers/n15/spectral.py:68`、`certifiers/n16/spectral.py:221` |
| 上側の値 (`rigorous_upper_witness`) | 上側証人点での明るさを、表の桁数で **切り上げた** 値 | `docs/data-schema.md`（`rigorous_upper_witness` の節）、`scripts/regenerate_certified_results.py:109-120` |
| 外向き丸め・切り上げ (outward rounding) | 上限として使う数は、丸めるときに必ず大きい方へ丸めること。小さい方に丸めると上限でなくなる。この版で 18 行が直された | `scripts/certificate_lib.py:148`、`docs/errata-v1.0.1.md:19-34` |
| 幅 (`interval_width`) | 上側の値と下限の差。本当の最小値はこの幅の中にある | `scripts/regenerate_certified_results.py:122-123` |
| `assert` | 「これが成り立っていなければここで止まれ」という命令。証明プログラムは最後に 4 つの `assert` で自分の結果を確かめる | `certifiers/n15/spectral.py:243-246` |
| `status: CERTIFIED` / `NOT_CERTIFIED` | 証明プログラムが最後に表示する結果。成功なら `CERTIFIED` | `certifiers/n15/spectral.py:223` |

## 3. 検査・再現に関する言葉

| 用語 | やさしい説明 | 根拠 |
| --- | --- | --- |
| 再実行 (replay) | 証明プログラムをもう一度動かして、同じ結果になるか確かめること | `scripts/verify_all.py:1-20` |
| クリーンルーム再実行 (clean-room replay) | 公開物を新しい場所に展開し直して、そこから 88 本すべてを実行したこと。記録が `evidence/full-cleanroom-replay/` にある | `evidence/full-cleanroom-replay/PUBLIC_REPO_FULL_REPLAY.md:1-11` |
| 保存済み出力 (saved replays) | 証明プログラム 1 本ごとの、過去の画面出力の写し | `evidence/saved-replays/n15/spectral.txt` |
| `--quick` / `QUICK_NS` | 速い確認用に選んだ 5 つの `n`（14, 15, 21, 36, 52）だけを実行すること | `scripts/certificate_lib.py:58` |
| `--all` / `EXPECTED_NS` | 公開している 44 の `n` すべて | `scripts/certificate_lib.py:53` |
| 成功契約 (success contract) | 実行を「成功」と数える条件の決まり。終了コード 0、時間切れでない、`status: CERTIFIED` がちょうど 1 行、エラー出力に状態の行が無い、`NOT_CERTIFIED`・`FAILED` が無い、さらに出力された数値が証明プログラムと合うこと | `scripts/verifier_runner.py:1-35`, `:117-142` |
| 終了コード (return code) | プログラムが終わるときに返す数。0 なら正常終了 | `scripts/verifier_runner.py:125-126` |
| 時間切れ (timeout) | 決めた時間（既定 1800 秒）を過ぎても終わらなかったこと。失敗扱い | `scripts/verify_one.py:29`、`scripts/verifier_runner.py:123-124` |
| `-B` | Python に `__pycache__`（下記）を作らせないための指定。このリポジトリのコマンドには必ず付ける | `README.md:80-81` |
| `__pycache__`, `.pyc` | Python が自動で作る一時ファイル。`check_release.py` はこれがあると「梱包の不備」として失敗にする | `scripts/check_release.py:21-22` |
| `-O`, `PYTHONOPTIMIZE` | Python の最適化モード。`assert` が消えてしまうため、実行スクリプトは起動を拒否する | `scripts/verifier_runner.py:90-107` |
| `PYTHONHASHSEED=0` | Python の内部の乱数の種を固定する設定。実行のたびの違いを減らす | `scripts/verifier_runner.py:105`、`.github/workflows/smoke-test.yml:10-11` |
| 入口の検査 (entry-point check) | 証明プログラムの `main()` が、本当に証明を実行してから結果を表示する形になっているかを、実行せずに文章として調べる検査 | `scripts/certificate_lib.py:1081-1104`（説明部分のみ読んだ。検査の本体は未確認） |
| AST（抽象構文木） | プログラムを実行せずに、文章として分解したもの。検査スクリプトは証明プログラムをこの形で読み、許可した書き方以外があれば止まる | `scripts/certificate_lib.py:1-31`, `:540-559` |
| 許可リスト (allow-list) | 「これだけは認める」という一覧。それ以外は拒否する。例: 証明プログラムが `import` してよいのは `__future__`, `decimal`, `fractions`, `heapq`, `typing` だけ | `scripts/certificate_lib.py:540` |
| 意味の一貫性検査 (semantic consistency) | 座標ファイル・2 本の証明プログラム・CSV・JSON・過去の記録が、同じ内容を言っているかを照らし合わせる検査 | `scripts/check_semantic_consistency.py:1-12` |
| 変異テスト (mutation test) | 一時的な複製の中でわざと 1 か所壊し、検査がそれに気づくか（しかも正しい理由で）を確かめるテスト | `tests/support.py:1-5`、`tests/test_semantic_consistency.py` 冒頭 |
| 監査ラウンド (round 3〜6 hardening) | これまでの見直しの回ごとに、見つかった抜け穴を塞いだ記録。テストのファイル名になっている | `tests/test_round3_hardening.py`〜`tests/test_round6_hardening.py` の冒頭 |

## 4. 改ざん防止・版に関する言葉

| 用語 | やさしい説明 | 根拠 |
| --- | --- | --- |
| SHA-256・指紋 (hash, digest) | ファイルの中身から計算する 64 桁の英数字。1 文字でも変わると全く別の値になるので、改ざんや破損に気づける | `scripts/manifest_policy.py:65-70` |
| `SHA256SUMS`（マニフェスト） | 決めた範囲の全ファイルの指紋一覧。リポジトリを変えるたびに作り直すもの | `MANIFEST_POLICY.json`、`docs/manifest-policy.md:1-6` |
| `MANIFEST_POLICY.json` | `SHA256SUMS` に入れる範囲の定義。`docs/` や `.github/` は範囲外 | `MANIFEST_POLICY.json`、`docs/manifest-policy.md:22` |
| 凍結コーパス (frozen corpus) | 数学の本体である 531 ファイル（証明プログラム 88、座標 88、過去の記録 355）。v1.0.1 のときから一切変えない | `docs/frozen-corpus.md:1-20`、`scripts/check_frozen_corpus.py:82-87` |
| 凍結一覧 (`data/frozen-corpus-v1.0.1.sha256`) | 凍結 531 ファイルの指紋の読みやすい写し。これ自体もファイルなので書き換えられる。だから最終的な根拠にはしない | `data/frozen-corpus-v1.0.1.sha256` 冒頭、`docs/frozen-corpus.md:24-48` |
| Git アンカー (git anchor) | Git に保存された v1.0.1 の中身そのものを根拠にすること。`--require-git-anchor` を付けると、それが読めないときは失敗にする | `scripts/check_frozen_corpus.py:1-55` |
| `git replace` | Git の機能で、ある中身を別の中身にすり替えて見せられる。検査はこれを無効にして読む | `scripts/check_frozen_corpus.py:13-23` |
| タグ (`v1.0.0`, `v1.0.1`) | 公開した版に付けた名札。`v1.0.1` はコミット `d92992101ca45a5cd755b8d962652ab7e4329973` を指す。凍結の検査とテストの 1 件がこれを必要とする | `scripts/check_frozen_corpus.py:76-77`、`PUBLICATION_STATUS.md` |
| `fetch-depth: 0` | GitHub の自動実行で、全履歴とタグを取ってくる設定。凍結の検査に必要 | `.github/workflows/smoke-test.yml:21-24` |
| リリース ZIP (canonical ZIP) | 公開時に手作業で添付した正式な ZIP と、その指紋ファイル。文書や自動実行の設定まで含めて守るのはこちら | `PUBLICATION_STATUS.md`、`release-assets/README.md` |
| 改行コード（LF / CRLF）・`* -text` | 行の終わりの記号の種類。Git が勝手に変えると指紋が変わるので、`.gitattributes` で変換を止めている。`data/certified-results.csv` は CRLF | `.gitattributes:1-17` |
| 生成物 (build product) | 手で書かず、スクリプトで作るファイル。`data/certified-results.csv` と `.json` がこれ | `docs/data-schema.md:1-11` |
| 正誤表 (errata) | 公開後に見つかった誤りと、その訂正の記録 | `docs/errata-v1.0.1.md` |
| Unreleased | `CHANGELOG.md` で、まだ版として公開していない変更をまとめた見出し | `CHANGELOG.md:3` |

## 5. 表に出てくる状態の名前

`data/certified-results.csv` の `external_status` 列と `notes` 列の値です（値の種類と件数は CSV を読んで数えました）。それぞれの細かい定義は文書には見当たらず、下の説明は値の名前と `docs/supersession-map.md`・`docs/external-status.md` からの読み取りです。

| 値 | やさしい説明 | 件数 |
| --- | --- | ---: |
| `EMAIL_SUBMITTED` | 記録ページの管理者にメールで送った | 26 |
| `DIRECT_OFFICIAL_LISTING_CONFIRMED; EMAIL_SUBMITTED` | メールで送り、記録ページに載ったことも確認した（`n=14, 15`） | 2 |
| `INTERNAL_ONLY_NOT_SUBMITTED` | 送っていない、このリポジトリだけのもの（`n=37` 以降） | 16 |
| `CERTIFIED_FIXED_CONFIGURATION_EXCEEDS_DISPLAYED_FIGURE` など `notes` 列の値 | その配置についての短い注記（改善した・据え置いた・非対称で改善した等）。正確な定義は **未確認** | — |
| `full_replay_status` = `CERTIFIED` | 保存されたクリーンルーム再実行で、2 本とも成功している | 44 |

# Rust プロトタイプの公開準備

更新日：2026-10-12。アプリ実装以外の現行タスクをここへ集約する。測定実装は [PLAN](PLAN.md)、判断基準は [現在の方針](../CURRENT_DIRECTION.md)、旧版の所在は [移行資料](../RUST_REWRITE_PREPARATION.md) を参照する。

**現在は準備段階。** PRのbaseは`rewrite/rust`のまま。mainマージ、既定ブランチ設定、タグ、Release、Pagesの実デプロイは別途依頼された段階で行う。以下の「整備済み」はファイル上の状態を表し、GitHub上のCI成功や公開済みを意味しない。

## main移行前のタスク

| 優先 | 項目・対象 | 現状と次の完了条件 |
| --- | --- | --- |
| P0 | 利用者向けREADME（日英） | 機能・起動・確認範囲・旧版リンクを整備済み。マージ対象の実装と表記を最後に照合する |
| P0 | Rust CI | Linuxのfmt／Clippy／通常・QA・GUIなし数値・回帰テストと、Rustソース・依存・workflow変更時のRust 1.95確認を必須`lint-and-test`へ集約。3 OSの通常releaseビルドとmacOS／WindowsのQAテストは別の任意チェック。Rust依存・targetキャッシュを導入済み。GitHubの対象SHAで成功と実行時間を確認する |
| P0 | Web CI | Ruff・Markdown lintを常時実行し、新旧MkDocs strict・サイトテスト／ビルド・URL保持確認・previewは関連変更時に実行。mainでは公開成果物を毎回ビルドし、必須チェック成功後に独立deployジョブで公開する |
| P0 | 旧版の公開継続 | 下記URL構成と旧版ラベルを整備済み。統合成果物の全旧HTMLルート・画像・言語切り替えを比較し、公開前に主要導線を確認する |
| P0 | 既存workflowの整理 | Rust・文書・actionlint・Pagesを`ci.yml`へ統合。開発ブランチのPush実行を外しPRの重複を解消、古いPR実行をキャンセル。必須名`lint-and-test`／`docs-lint`／`actionlint`とmainの既存rulesetを維持。対象SHAの実行結果が一致することを確認する |
| P0 | コミュニティ文書 | CONTRIBUTING、Security Policy、版・測定条件を区別するIssueフォーム、PRテンプレートを整備済み。サポート表記に配布・実機保証を混ぜない |
| P0 | 履歴・ブランチ・GitHub設定 | `v0.9.1`の参照先と`archive/python-v0.9.1`はremoteで同じ`b7a10b1a`を保持。mainとの差分・未統合のRust作業を確認し、必要な保護ルール・Pages環境を設定してから依頼された移行を実行する |
| P0 | 移行時のリンクと運用 | main移行コミットでAGENTS／CONTRIBUTING／README／オンライン文書の`rewrite/rust`を更新。clone手順・CI badge・Dependabot・PR base・Required checks・リポジトリ説明をmain運用に揃える |

## CIの運用ポイント

`ci.yml`はmain／rewrite/rust宛のPRとmainへのPush、手動実行を扱う。開発ブランチへのPushでは起動せず、PRのマージ結果を1回検証する。PRなしでrewrite/rustへ直接変更した場合は手動実行が必要。新しいコミットが来たPRの旧実行はキャンセルし、mainで実行中のPages公開は中断しない。Scorecardは独立したセキュリティ評価として維持する。

| 区分 | 検証と条件 | マージの扱い |
| --- | --- | --- |
| `lint-and-test` | Rust変更時にLinuxのfmt、全ターゲット・全機能Clippy、GUIなし／通常／QAの全数値・回帰テスト、QA doctest。Rustソース・依存・toolchain・workflow変更時はRust 1.95の全ターゲット確認も実行 | 必須。選択したジョブの失敗・キャンセル・想定外のスキップは不合格 |
| `docs-lint` | RuffとMarkdown lintは常時。公開マニュアル・サイト・依存・生成スクリプト・workflow変更時に新旧MkDocs strict、サイトテスト／ビルド、URL保持確認とpreview | 必須。関連変更がない場合は静的チェックだけで完了 |
| `actionlint` | 全workflowの構文・式・シェルを常時確認。版指定とチェックサム確認を維持 | 必須 |
| `compatibility` | Rust変更時に3 OSの通常desktop releaseをビルド、macOS／WindowsではQAの全テストも1回実行 | 任意。失敗は表示し、OS固有の変更や配布前は結果を確認する |
| 性能・実機評価 | 手動CIの`benchmarks`指定でLinuxの反復bench。120／600秒の実時間・GPU・外部I/O・実機評価は専用のローカル手順 | PRの必須条件から分離。段階4と公開候補の確認条件は維持する |

workflow全体のpathsフィルターは使わず、必須ステータスを文書だけのPRでも返す。`scripts/ci_changes.py`はGit差分をNUL区切りで読み、削除・改名も判定する。履歴を取得できない場合、未知のビルド入力、手動実行は全検証へ戻す。文書のみのRustジョブ省略は判定成功と明示的な非対象を条件にし、判定失敗や空の出力を成功扱いしない。判定の回帰テストもCIで実行する。

RustキャッシュはCargo registryと依存のtarget成果物を保持し、OS／Rust版／ジョブ／Cargo.toml・Cargo.lock・コンパイル環境の違いで区別する。アプリ自体は毎回ビルドし直し、キャッシュヒットを検証の代用にしない。CIのみdev／testのデバッグ情報とincrementalを無効にし、成果物容量と転送を抑える。npm／pipのキャッシュも維持する。最初の実行はキャッシュがなく、ツールチェーン・依存更新時も再コンパイルが発生する。[rust-cacheの仕様](https://github.com/Swatinem/rust-cache) と [GitHubのキャッシュ範囲](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows#restrictions-for-accessing-a-cache) を参照する。

PRで保存したキャッシュは同じPRの再実行用で、別のPRへ直接共有されない。main移行前はrewrite/rustを選んで手動CIを1回成功させると、以後このブランチ宛のPRが復元できる依存キャッシュを用意できる。main移行後はmainのPush実行で共通キャッシュを更新する。

数値テストのassertion、全FFTサイズ・窓・精度と許容差は削減しない。`cargo test --all-targets`が起動するharnessなしbenchは各条件1回にし、`cargo bench`だけが従来の200／1,000／10,000回の反復とp95計測を行う。テスト時の1回分の時間は性能の合格判定に使わない。[Cargoのターゲット選択](https://doc.rust-lang.org/cargo/commands/cargo-test.html#target-selection) と [benchの起動引数](https://doc.rust-lang.org/cargo/commands/cargo-bench.html#description) を参照する。

mainの既存rulesetが要求する`lint-and-test`、`docs-lint`、`actionlint`の名前は変更しない。任意releaseビルドはこれらの依存関係に含めず、`continue-on-error`で失敗を隠さない。Pagesのjob IDは`build`を維持し、公開はmainの新旧サイトビルドと3つの必須チェック成功後に限定する。必須チェック設定を変更するときは、実際にGitHubが返したチェック名を確認し、推測した名前だけで設定しない。

## 初回プロトタイプ配布前のタスク

| 優先 | 項目 | 完了条件 |
| --- | --- | --- |
| P1 | 版番号・タグ・互換性 | 次のRustアプリ版は`v0.10.0`。CargoとmacOSバンドルをこの版へ揃え、Python最終版と配布用`version.json`は`v0.9.1`を保持。タグ衝突とGitHub Latestの扱いを確認し、設定／結果JSONのスキーマ版とアプリ版を区別したリリースノートを作る |
| P1 | OS／CPUと配布形式 | まず検証できる対象だけを選ぶ。macOSの.app／DMG、WindowsのZIP／インストーラー、Linuxの形式・ランタイム依存を定義し、クリーン環境で起動・入力許可・保存を確認する |
| P1 | Rust専用の配布ビルド | 通常desktopを`--locked`・qaなしでビルド。アプリの版・アイコン・ライセンス・依存ライセンス・成果物名・SHA-256を揃える。macOSの現行スクリプトはCargoから版を取得するローカル用で、アイコン等を配布用へ整える |
| P1 | Release workflow | 検証済みSHAから成果物を作り、再実行で混在しないようにする。署名／公証の方針を決め、必要な資格情報はCIの限定した権限・環境へ置く。タグ作成・公開の依頼までは自動公開を導入しない |
| P1 | ダウンロードの新旧選択 | Pythonを固定で残し、Rustと明示的に切り替えられるメタデータ・成果物選択テストを作る。単一`version.json`をRustへ差し替えるだけで旧版導線を壊さない |
| P1 | 利用者向け文書の拡充 | 実際のRust画面、OS別の起動・権限・入力不在、測定単位・校正境界・保存形式、既知の制限を追加。旧Python画像・デモをRustの画面として流用しない |
| P1 | 公開候補の受け入れ | [PLANの段階4](PLAN.md#4software-loopbackとlock-inによる品質評価) の確認範囲を確定し、対象OSで通常起動→Software Loopback／実入力→停止→保存・復元を確認。Lock-in未完了なら実験段階の表記を維持する |

配布版と性能・精度の検証対象SHAを一致させる。CIのビルド成果物、ローカル.app、署名・配布を確認したインストーラーは区別する。旧VirusTotal処理はアップロード結果だけで「重大なマルウェアなし」と記していたため継承しない。再導入する場合は、対象タグの明示と実際の解析状態・結果の表示を条件にする。

段階4.5のGeneratorを含む公開候補では、[基本設計の受け入れ条件](GENERATOR_DESIGN.md#受け入れ試験) も対象SHAで確認し、通常版の出力先・レベル・開始／停止・切断・復元と対応OSの制限を文書へ反映する。計画を追加しただけでは実装済みとせず、公開時期・main移行・配布用`version.json`の変更判断とも分ける。

## 公開後・継続運用

* P2：文書用Python依存の版固定／更新手順、CIの初回／キャッシュ復元後の実行時間とキャッシュ容量、Cargo依存の脆弱性・ライセンス確認を運用に合わせて整える。Dependency更新を全自動でマージしない。
* P2：OS別のGPU／音声・長時間試験を定期的に再実行できる環境を用意する。共有runnerの単体テストと実機試験を分け、ログに対象SHAと条件を保存する。
* P2：旧版のリンク切れ・文書ビルド環境を保守する。旧Python機能追加は再開せず、原本の意味とURLを維持する。削除候補の技術資料はリンク・測定上の参照価値を確認してからGit履歴へ委ねる。

## 新旧マニュアルとPagesの構成

| 公開先（`/MeasureLab/`以下） | ソース | 維持すること |
| --- | --- | --- |
| `/`・`/en/`と既存の各ページ | `docs/`、`mkdocs.yml` | Python v0.9.1の本文・画像・検索・深いリンク。全ページに旧版ラベルとRustへのリンク |
| `/rust/`・`/rust/en/` | `docs-rust/`、`mkdocs-rust.yml` | Rustで現在使える機能・クイックスタート。検索とナビを旧版から分離 |
| `/download/`・`/version.json` | `download-site/`・`version.json` | 現在配布しているPython v0.9.1。Rust配布開始時もPythonへの導線を保持 |

旧版を別ディレクトリへ一括移動しないため、既存ブックマークを維持できる。将来トップを新しい案内へ変える場合も、旧ルートの互換性を別途設計する。旧版PDFの自動生成は退役し、WebビルドからPDFプラグインとWeasyPrint依存を外した。既存ReleaseのPDF資産は削除しない。

```sh
source .tools/env.sh
npm --prefix download-site ci
npm --prefix download-site test
./.venv/bin/python scripts/build_pages.py
```

`scripts/build_pages.py`は旧マニュアル→Rustマニュアル→downloadの順で`site/`へ組み立てる。MkDocsのcleanが子サイトを消さないようこの順序を共通化し、全旧Markdownページの日英ルート・主要資産・旧版ラベルと配布版JSON、全生成HTMLの内部リンクを検証する。PRでは成果物を確認できるだけで公開しない。**mainへマージするとPagesは自動更新される**ため、その前にこの構成を確認する。

公開設定は [GitHub Pagesの公式手順](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)、複数設定と出力先は [MkDocs設定](https://www.mkdocs.org/user-guide/configuration/) を参照する。CI結果、ブラウザ確認、実機試験の未実施を成功扱いしない。

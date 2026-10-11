# Rust プロトタイプの公開準備

更新日：2026-10-11。アプリ実装以外の現行タスクをここへ集約する。測定実装は [PLAN](PLAN.md)、判断基準は [現在の方針](../CURRENT_DIRECTION.md)、旧版の所在は [移行資料](../RUST_REWRITE_PREPARATION.md) を参照する。

**現在は準備段階。** PRのbaseは`rewrite/rust`のまま。mainマージ、既定ブランチ設定、タグ、Release、Pagesの実デプロイは別途依頼された段階で行う。以下の「整備済み」はファイル上の状態を表し、GitHub上のCI成功や公開済みを意味しない。

## main移行前のタスク

| 優先 | 項目・対象 | 現状と次の完了条件 |
| --- | --- | --- |
| P0 | 利用者向けREADME（日英） | 機能・起動・確認範囲・旧版リンクを整備済み。マージ対象の実装と表記を最後に照合する |
| P0 | Rust CI | 3 OSのfmt／Clippy／通常・QA・GUIなしテスト／通常releaseビルド、LinuxのRust 1.95チェックを定義済み。GitHubの対象SHAで全ジョブ成功を確認する |
| P0 | Web CI | 新旧MkDocs strictビルド・サイトテスト／ビルド・Ruff・Markdown lint・URL保持確認をPRで実行し、previewを保存する構成を整備済み。公開はmainからの独立deployジョブのみ |
| P0 | 旧版の公開継続 | 下記URL構成と旧版ラベルを整備済み。統合成果物の全旧HTMLルート・画像・言語切り替えを比較し、公開前に主要導線を確認する |
| P0 | 既存workflowの整理 | サイト検証をPages buildへ統合。退役したRelease依存のVirusTotal workflowを削除。actionlintは版指定・チェックサム確認へ変更。GitHubの必須チェック設定に旧job名が残らないか確認する |
| P0 | コミュニティ文書 | CONTRIBUTING、Security Policy、版・測定条件を区別するIssueフォーム、PRテンプレートを整備済み。サポート表記に配布・実機保証を混ぜない |
| P0 | 履歴・ブランチ・GitHub設定 | `v0.9.1`の参照先と`archive/python-v0.9.1`はremoteで同じ`b7a10b1a`を保持。mainとの差分・未統合のRust作業を確認し、必要な保護ルール・Pages環境を設定してから依頼された移行を実行する |
| P0 | 移行時のリンクと運用 | main移行コミットでAGENTS／CONTRIBUTING／README／オンライン文書の`rewrite/rust`を更新。clone手順・CI badge・Dependabot・PR base・Required checks・リポジトリ説明をmain運用に揃える |

新CIはmainとrewrite/rustを対象にし、必須チェックを文書だけのPRでも返せるようpathsフィルターを外している。必須候補は`check (ubuntu-latest)`、`check (macos-latest)`、`check (windows-latest)`、`msrv`、Pagesの`build`、`actionlint`。実際にGitHubが返したチェック名を確認して保護設定へ登録し、推測した名前だけで設定しない。

## 初回プロトタイプ配布前のタスク

| 優先 | 項目 | 完了条件 |
| --- | --- | --- |
| P1 | 版番号・タグ・互換性 | Cargoの`0.1.0`とPythonの`v0.9.1`をどう区別するか決定。タグ衝突とGitHub Latestの扱いを確認し、設定／結果JSONの版とアプリ版を区別したリリースノートを作る |
| P1 | OS／CPUと配布形式 | まず検証できる対象だけを選ぶ。macOSの.app／DMG、WindowsのZIP／インストーラー、Linuxの形式・ランタイム依存を定義し、クリーン環境で起動・入力許可・保存を確認する |
| P1 | Rust専用の配布ビルド | 通常desktopを`--locked`・qaなしでビルド。アプリの版・アイコン・ライセンス・依存ライセンス・成果物名・SHA-256を揃える。macOSの現行スクリプトはローカル用で、版固定・アイコン等を配布用へ整える |
| P1 | Release workflow | 検証済みSHAから成果物を作り、再実行で混在しないようにする。署名／公証の方針を決め、必要な資格情報はCIの限定した権限・環境へ置く。タグ作成・公開の依頼までは自動公開を導入しない |
| P1 | ダウンロードの新旧選択 | Pythonを固定で残し、Rustと明示的に切り替えられるメタデータ・成果物選択テストを作る。単一`version.json`をRustへ差し替えるだけで旧版導線を壊さない |
| P1 | 利用者向け文書の拡充 | 実際のRust画面、OS別の起動・権限・入力不在、測定単位・校正境界・保存形式、既知の制限を追加。旧Python画像・デモをRustの画面として流用しない |
| P1 | 公開候補の受け入れ | [PLANの段階4](PLAN.md#4software-loopbackとlock-inによる品質評価) の確認範囲を確定し、対象OSで通常起動→Software Loopback／実入力→停止→保存・復元を確認。Lock-in未完了なら実験段階の表記を維持する |

配布版と性能・精度の検証対象SHAを一致させる。CIのビルド成果物、ローカル.app、署名・配布を確認したインストーラーは区別する。旧VirusTotal処理はアップロード結果だけで「重大なマルウェアなし」と記していたため継承しない。再導入する場合は、対象タグの明示と実際の解析状態・結果の表示を条件にする。

## 公開後・継続運用

* P2：文書用Python依存の版固定／更新手順、CIキャッシュと実行時間、Cargo依存の脆弱性・ライセンス確認を運用に合わせて整える。Dependency更新を全自動でマージしない。
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

# Rust プロトタイプの公開準備

Rust版は`main`へ統合済みで、開発PRのbaseも`main`とする。ここには配布前の未完了条件と公開運用を置く。測定機能の受け入れは [PLAN](PLAN.md)、実機の確認範囲は [VALIDATION](VALIDATION.md) を参照する。mainへの統合、CIビルド、ローカル.app作成を配布済みとは扱わない。

## 初回プロトタイプ配布前のタスク

| 項目 | 完了条件 |
| --- | --- |
| 版番号・互換性・リリースノート | 次のRust版は`v0.10.0`。Cargoとバンドルの版、設定／結果スキーマの互換性、タグ衝突・GitHub Latestの扱いを確認する。Pythonの配布用`version.json`は別途配布変更まで`v0.9.1`を保持 |
| 対応OS／CPU・配布形式 | 検証できる対象を選び、macOS .app／DMG、Windows ZIP等、Linuxの形式・ランタイム依存を定義。クリーン環境で起動・入力許可・保存を確認 |
| 配布ビルド・Release workflow | 検証済みSHAの通常desktopを`--locked`・qaなしでビルドし、アイコン・版・ライセンス・成果物名・SHA-256を揃える。署名／公証・再実行時の混在防止を定義。タグ・公開は依頼された段階で実行 |
| ダウンロードの新旧選択 | Pythonを固定で残し、Rustへ明示的に切り替えるメタデータ・成果物選択テストを用意。単一`version.json`の置換で旧版導線を壊さない |
| 利用者向け文書 | Rustの実画面、OS別の起動・権限・入力不在、単位・校正境界・保存形式・既知の制限を実装と照合。旧Python画像をRustへ流用しない |
| 公開候補の受け入れ | 対象SHAで通常起動→内部／実入出力→停止→保存・復元を確認。Generatorのレベル・切断・OFF復元、同期比較の確認範囲を明記。未確認機能は実験段階の表記を維持 |
| GitHub上の確認 | 対象SHAの必須CI、関連するOS別ビルド、Pages公開結果と主要導線を確認。ローカル検証でremoteの成功を推測しない |

配布版と性能・精度の検証対象SHAを一致させる。旧VirusTotal処理を再導入する場合は、アップロードだけで安全判定せず、対象タグと実際の解析状態・結果を表示する。

## CIの運用ポイント

実行条件とコマンドの正本は [ci.yml](../../.github/workflows/ci.yml)、変更分類は [ci_changes.py](../../scripts/ci_changes.py) と [回帰テスト](../../scripts/test_ci_changes.py)。ローカル手順は [Tool Usage Guide](../../.agents/workflows/tool_usage.md)。main宛PRとmainへのPush、手動実行を使い、PRの旧実行はキャンセルする。mainのPages公開は中断しない。

| ステータス | 役割 |
| --- | --- |
| `lint-and-test`（必須） | Linuxのfmt・全ターゲット全機能Clippy・GUIなし／通常／QAテスト・doctest。関連変更ではRust 1.95の全ターゲット確認も実行 |
| `docs-lint`（必須、job IDは`build`） | Ruff・Markdown lintは常時。関連変更で新旧MkDocs strict、サイトテスト／ビルド、URL・内部リンク検証、preview |
| `actionlint`（必須） | workflow構文・式・シェルを確認 |
| `compatibility`（任意） | 3 OSの通常desktop release、macOS／WindowsのQAテスト。OS固有変更・配布前に結果を確認 |
| 性能・実機評価 | 手動の反復benchとローカルQA。共有runnerの数値テストとは別に判定 |

必須名は保護ルールとの互換性のため維持する。workflow全体のpathsフィルターで必須ステータスを消さない。関連変更がない場合の省略は変更分類の成功を前提とし、判定失敗・履歴不足・未知入力は全検証へ戻す。任意ビルドの失敗を隠さない。

依存キャッシュはOS・Rust版・依存・コンパイル環境を区別し、mainのPushで更新する。キャッシュヒットは検証の代用にしない。数値テストの条件・許容差は減らさず、`cargo test`のbenchは各条件1回の動作確認、反復性能は`cargo bench`で評価する。保護ルール変更時はGitHubが返した実際のチェック名を確認する。

## 新旧マニュアルとPages

| 公開先（`/MeasureLab/`以下） | ソース | 維持するもの |
| --- | --- | --- |
| `/`・`/en/`と既存ページ | `docs/`、`mkdocs.yml` | Python v0.9.1の本文・画像・検索・深いリンク、旧版ラベルとRustへのリンク |
| `/rust/`・`/rust/en/` | `docs-rust/`、`mkdocs-rust.yml` | 現在使えるRust機能、独立した検索・ナビ |
| `/download/`・`/version.json` | `download-site/`、`version.json` | 現在配布中のPython v0.9.1。Rust配布開始時もPythonへの導線を保持 |

[build_pages.py](../../scripts/build_pages.py) が旧マニュアル→Rust→downloadの順で`site/`へ組み立て、旧ページの日英ルート・主要資産・旧版ラベル・配布JSONと全生成HTMLの内部リンクを検証する。旧版を別ディレクトリへ移さない。PDF自動生成は退役済みで、既存ReleaseのPDF資産は保持する。

PRはpreviewを作る。**mainへマージするとPagesが自動更新される**。公開は新旧サイトビルドと必須3チェックの成功後に限る。タグ・アプリのReleaseとは別の運用である。

## 継続運用の課題

* 文書用Python依存の版固定・更新、CI初回／キャッシュ復元後の時間・容量、Cargo依存の脆弱性・ライセンス確認を整える。依存更新を全自動でマージしない。
* OS別のGPU／音声・長時間試験を再実行できる環境を用意し、対象SHAと条件をQA成果物に保存する。
* 旧版のURLと原本の意味を維持する。Pythonアプリの機能追加・旧テスト環境の復元は再開しない。

# 0019: 移行中のCIと保存参照の境界

日付: 2026-10-01。Rust/QMLの採用判断は変更しない。

## 問題

Python CIがRust候補を `--offline --locked` でビルドし、クリーンなrunnerにCargoの依存が
ないため失敗していた。Native evaluationではcore-v1の校正CSVが `.gitignore` の
`*.csv` に該当し、checkoutに含まれず保存結果の比較が失敗していた。
候補テストの一部は作成時のOS・インストール済みpackage全体を要求しており、
別OSでのCI比較に適した既存のportableモードを使っていなかった。

## 決定

* 現行Python版の回帰・数値参照を維持する。移行で比較基準として使うFFT、校正、
  JSON/CSV保存、履歴、取得、routeのテストは削除しない。
* Rust実行ファイルを使うテストに `native` markerを付け、通常CIでは
  `-m "not native"`、Native evaluationのprobe-coreでは `-m native` を実行する。
  pure Rustのbuildと依存取得が成功した後に、実行比較と破損入力拒否を検査する。
* Pythonだけの参照・証拠検証は通常CIに残す。専用CIへの移動をskipによる成功扱いにしない。
* CIの候補比較は既存のportableモードを明示する。元fixture、source hash、
  理論値との比較、数値許容差、メタデータ検証は維持する。固定環境の検査はrunnerに残す。
* core-v1のCSVをignoreから除外し、保存済みmanifestのSHA-256に一致する元データを登録する。
  CIで期待値を再生成しない。
* 移行テストとmarker設定の変更でNative evaluationが起動するようpathを整理する。
  移行ブランチ同士のPRでも両CIを実行し、後続作業を含まない修正差分を検査できるようにする。

## 検証範囲

両Pythonテスト範囲、Rust coreのテスト・format・Clippy、通常のRuff・Mypy・翻訳・Markdown・
全言語UIサイズを確認する。Qtの独立CIもPR上で確認する。
実機、長時間運転、rendererのGPU性能試験はこの修正の合格条件に加えない。

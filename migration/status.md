# Rust core段階導入の現在地

更新: 2026-10-04。MIG-008の統合・短い比較・四案の判断は完了。
[判断0037](decisions/0037-mig008-integrated-evaluation.md)によりRust/QMLの一括展開を見送り、
現行Spectrum Analyzer一つへのRust FFT／共有result接続を次の対象とする。
Python binding・製品への組込み・切替は未実施。工程の正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。

## 再開の入口

`git status --short --branch`と変更対象のコードを確認し、[native手順](../native/README.md#buildと検証)で
必要なcrateをbuild／testする。worktree専用のRust 1.98.1と現行GUIの`.venv/`は保持する。
Qt SDK・CMake/Ninja・CPAL/PortAudioの開発依存は不要。
MIG-008の全条件再実行や別環境構築は先行条件にしない。
Windows・ARM、clean配布、延期した機能・機器条件は未確認。長時間試験は行わない。

## 保存済みの評価記録

MIG-008の実施条件・能力差・失敗と修正・四案の理由は判断0037へ集約した。
代表CPAL/CXX-Qt/BlackHole 2chと保存4/8chが成功した。
30秒比較ではnativeのCPU 33.95秒／RSS 104.4 MiB／表示約10.7回毎秒に対し、
Pythonは28.33秒／171.6 MiB／約31.2回毎秒。条件差があり、一律の速度比には使わない。
段階導入の性能利益は未検証。

最終report 5件と関連失敗、対応表は`.migration-local/evidence/2026-10-04-mig008/`に保持する。
成功reportは`saved-final`、`live-final`、`languages-final`、`runtime-final`、`edits-final`の
各`report.json.gz`。`index.json`には当時のcommand・条件・hashを保持する。
比較を支える元logは`.migration-local/benchmarks/mig008-runtime-v3/raw-logs.json.gz`と
`mig008-edits-v2/raw-logs.json.gz`へ内容一致を確認して圧縮した。
旧artifactパスとsource hashは当時の記録であり、現在の再実行手順ではない。

削除したQt試作の未コミット変更は同evidence directoryの
`retired-ui-working-tree.patch.gz`と`retired-ui.json`に保持する。
今回削除したコミット済みコード・旧計画・詳細記録はGit履歴`75581059`から取得できる。
既存の`2026-10-03-before-main-untracked/`のsource退避も保持した。

## MIG-008終了時の整理と検証

終了した移行評価のCLI／Python runner／テスト、台帳検査、旧backend試作、
重複した計画・手順・決定記録、拡張FFT・filter・route・校正の評価fixtureを削除した。
通常Python CIをmainの構成へ戻し、Rust CIはworkspaceの手動検証1ジョブへ集約した。
RustのDSP／graphと取得queue、履歴、Timebase、Trigger、校正、保存codec、その回帰テストは保持する。
[固定FFT参照](fixtures/README.md)18条件の入力・期待値・許容差を維持し、直接libraryから検証する。
manifestは短い表記に整形し、削除したscenario／exportへの参照を除いた。

依存版を変更せずRustのlockを117から36 packageへ縮小した（registry 33、workspace 3）。
不要なlocal Cargo source／archive／index 531項目、古いreport・重複表示／保存生成物、
build生成物と検証cacheを除去した。`.migration-local/`は約166 MiBから約17 MiBへ縮小。
必要なtoolchain・locked依存と現行GUIの依存は保持する。

Rust workspace 122テスト（固定FFT18条件を含む）、Rust format／Clippy、
Pythonスモーク37テスト、厳格な翻訳検査、Ruff lint／format、Markdown lintは成功。
Python全体のcollectionは1974件成功。mkdocs未導入のsecurity module 1件はcollection時にskip。
全体Pytestの実行と全言語UIサイズの再検証は今回行っていない。
音声・性能の再測定、他OS検証、remote CI、commit／push／PR／Issue／Project更新は行わない。

## 段階導入の境界調査と追加整理

2026-10-04、HEAD `b8c94da2`から調査・整理した。
次の実装境界をSpectrumの取得済み連続区間→ワーカーの一括解析→不変resultへ絞った。
コードの接続点、copy/所有権、数値・校正・世代の不足と実装順は
[評価計画の調査結果](../guide/RUST_QML_MIGRATION_PLAN.md#実装境界の調査結果)に記載する。

2ch f64 / N=4096 / Hannの短いlibrary計測では、Rustのplan毎回構築は中央値257.932 µs、
再利用は146.829 µs。現行Pythonの2ch FFTは42.388 µs、標準解析は214.812 µs。
計算範囲が異なるため言語間の速度比には使わない。Python境界・実GUIの性能利益は未検証。
新しいbinding、製品の切替、plan cacheの実装はこの調査では行っていない。

削除済み評価CLIだけが利用していたlegacy trace import adapterと専用テスト、
そのadapterだけが使ったmerged CSV読込分岐を除去した。
snapshotのJSON/独立CSV+sidecar codecと保存workerは保持し、
共用JSON parserの整数丸め防止テストはproduct codecのテストへ移した。
core、固定FFT参照、製品のPython/FFTW fallbackには変更を加えていない。
計測用source/buildはリポジトリ外の一時directoryを使い、常設runnerを追加しない。

対象graph-coreの104テスト、Rust format／対象crateのClippy（all-targets）、
Ruff lint／format、変更Markdownのlintは成功。
Python全体テスト、固定FFT全条件の再実行、全言語UIサイズ検証は今回行っていない。
レイアウト・翻訳の変更はなく、MIG-008統合・長時間・Windows/ARM・配布の再検証も行っていない。

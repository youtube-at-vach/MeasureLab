# 次期コア検証の進捗

更新: 2026-10-04。MIG-008の統合・短い比較・判断を完了。
次の方針は[判断0037](decisions/0037-mig008-integrated-evaluation.md)のRust core段階導入。
Rust/QMLの一括展開は見送り、製品への組込み・切替は未実施。
工程・完了条件は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)を正本とする。
Windows・ARMはMIG-008後へ延期。長時間試験は現在の計画から削除した。

## 現在地

| 項目 | 状態 |
| --- | --- |
| 作業場所 | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`、macOS Intel |
| branch / 基点 | `codex/migration-filter-qt`、今回の基準HEAD `edad0838`。統合先は`codex/next-core-evaluation` |
| 参照 | `9fd79958`（MeasureLab 0.9.0）。元fixture・係数・許容差を維持 |
| main同期 | 最終確認は2026-10-03、`84013a76`をmerge `0fe41a7a`で取込み |
| Git状態 | MIG-008の記録と方針決定後の整理は現在の未コミット差分。削除したQt試作の未コミット変更は圧縮patchへ保持。push/PR/Issue/Project更新は未実施 |
| MIG-001〜003 | 環境・契約・参照fixtureを作成済み |
| MIG-004〜007 | Intelの両Qt、両backend入力、共有FFT/履歴/Timebase、表示/Trigger/校正、CSV/JSON、固定filterの評価結果をMIG-008へ再利用 |
| MIG-008 | A: 代表2ch実入力と保存4/8ch成功。B: 各30秒・1回、core/表示編集各1回完了。C: 四案の判断を0037へ記録 |

004〜007の全tap、profile、他OS等の残項目をすべて完成させる前提は外した。
延期を検証済みとは扱わず、MIG-008の判断へ制約として添える。

## 次の作業

MIG-008の現在の対象範囲は完了した。
次の実装単位は、現行Spectrum Analyzer一つへのRust FFT/共有resultの接続評価。
Python境界のcopy・寿命・停止・校正付き保存と、現行rendererでの利益を確認する。
このbindingはまだ実装していない。QML全面展開や製品backend切替へ自動的には進めない。
Windows/ARM、延期した機能・配布条件は未確認のまま保持し、長時間試験は復活させない。

## 再開と検証

1. `git status --short --branch`、本書、変更対象のコードを確認する。
2. [native環境](../native/README.md#このworktreeで使う)で導入済みツールを有効にする。再導入・Hello world・全fixture再verifyは不要。
3. 0037の次の範囲を確認し、依頼された実装単位の変更と対象テストを進める。MIG-008の全条件再実行は不要。
4. 保存済みの評価reportを利用し、結果・未確認点と次の作業を本書へ短く記録する。Qt/rendererの旧runnerは削除済み。

関連手順は下表から必要なものだけ読む。環境の詳細は[参照環境](environment.md)。
新しい小変更ごとの手順書・決定記録、全source/binaryの複製や全artifact再監査は必須にしない。
Ruff lint/format、Markdown変更時のlintは[共通手順](../.agents/workflows/tool_usage.md)に従う。

## 再利用する証拠

既存の成功は記載条件の範囲だけを指す。MIG-008の統合・比較・採用判断の完了には置き換えない。

| 対象 | 結果と参照 |
| --- | --- |
| filter / 両Qt | 保存54実行、BlackHole24実行・48取得世代、raw回帰8実行成功。[決定0036](decisions/0036-filter-qt-integration.md)。Qt試作・手順は方針決定後に削除 |
| f32→f64境界 | 保存30条件×5 pattern、native両backend6実行成功。[実装](../native/graph-core/src/filter.rs) |
| PortAudio callback | BlackHole2/4/8chでPortAudio/CPAL各6実行・18世代成功。[実装](../native/portaudio-input/src/lib.rs) |
| 共通input.raw | 保存32条件、PortAudio3実行とCPAL/両Qt6実行成功。[実装](../native/audio-core/src/backend.rs) |
| 表示/Trigger/校正/保存 | Qt評価結果は[判断0037](decisions/0037-mig008-integrated-evaluation.md)へ保持。再利用する[Trigger](../native/graph-core/src/acquisition/trigger.rs)、[校正/result](../native/graph-core/src/result.rs)、[製品codec](../native/product-codec.md)は維持 |

最終結果と関連失敗のreport 25件は`.migration-local/evidence/`へgzipで保持した。
最新filter/Qtの5 reportはその`2026-10-03-filter-qt/`以下の
`saved-final-v2/report.json.gz`、`forward-final/report.json.gz`、`languages-final/report.json.gz`、
`live-final/report.json.gz`、`raw-trigger-final/report.json.gz`。
圧縮前後の内容一致を確認済み。対応表と元hashは`evidence/index.json`。
その時点のRust194件/関連Python304件と静的検査/UIサイズは成功。
途中の軸/replay/端点処理の失敗と修正は決定0036へ要約済み。

## MIG-008の今回の結果

同一区間の波形projection/切替、比較用の明示hop、既存runnerのcase/adapter選択と短い比較を追加した。
代表CPAL/CXX-Qt/BlackHole 2chは3取得世代、保存f32 4/8chは各1条件で成功。
校正・通常/Triggerの製品CSV/JSON再読込、失敗復帰、停止・再開・購読破棄・終了を確認した。
全9言語のCXX-Qt表示と製品UIサイズも成功。元fixture・係数・許容差は維持した。

4096点/代表2chの30秒比較ではnativeはCPU 33.95秒、peak RSS 104.4 MiB、表示更新約10.7回/秒。
Pythonは28.33秒、171.6 MiB、約31.2回/秒。
計算精度・窓・renderer・保存量・更新の観測方法に差があるため、一律の速度比にはしない。
native Hannの取得bytesと独立FFTは元許容差内で一致した。
core/表示編集は両経路各1回成功し、一時変更は元に戻した。
能力差・途中失敗・四案の判断と次の範囲は[0037](decisions/0037-mig008-integrated-evaluation.md)を正本とする。

最終report 5件と関連失敗は`.migration-local/evidence/2026-10-04-mig008/`へgzipで保持。
対応表は同directoryの`index.json`。実行/編集logは`.migration-local/benchmarks/`に保持した。
対象Rust 37件、関連Python 117件、Rust Clippy/format、Ruff lint/format、Markdown lintは成功。
Windows/ARM、remote CI、長時間試験は実施していない。

## 2026-10-04の整理

MIG-008の工程を統合・短い比較・判断へ集約した。
重複作業票/残工程表、詳細進捗履歴、完了済み試作の重複手順・決定記録と旧SDK記録を削除。
元文書はGit履歴`1bc1e21c`から取得できる。
古い中間アーティファクト445項目、重複source/binary/配布コピー、不要な検証用venvと生成物を削除した。
`.migration-local`は約75 GiBから約140 MiBへ縮小。独立rendererのbuildと導入時のsmoke/downloadも削除。
この整理時点ではQt SDK・toolchain・依存cache・主workspaceのbuild cacheを維持した。
方針決定後のQt SDK・生成物の整理は次節を参照。

旧report内のartifactパスとhashは当時の記録。対象の生データ・古い実行物は整理済みで再監査には使えない。
新たな比較は現在のコードと固定fixtureから実行する。
この整理時点ではNative CIの二重runnerを削除し、Qt実行を代表2chへ縮小した。

`.venv/`、`.tools/`、`.migration-local/`はGit管理外。
今回の計画整理では新たな音声/性能/他OS検証、push/PR/Issue/Project更新を行っていない。

## 方針決定後の整理

2026-10-04、判断0037のRust core段階導入に合わせ、Qt/QML・rendererの並列試作78ファイルを削除。
両Qtのprobe/display、表示用coreと模擬worker、QML、renderer spike、専用runner/テスト・手順・SDK定義が対象。
Rust workspaceとlock、Native CI、翻訳検査のQML対応、文書の参照を整理した。
不要になったRust依存51件と、QML専用翻訳104キーを全9言語から削除。他の依存版・翻訳値は維持した。
CPAL/PortAudioの入力境界、audio/DSP/graph core、Trigger/校正/保存codec、固定fixtureと圧縮reportは保持する。

元コードはGit履歴`edad0838`から取得できる。削除対象にあったMIG-008の未コミット差分は
`.migration-local/evidence/2026-10-04-mig008/retired-ui-working-tree.patch.gz`へ保存し、圧縮前後の一致を確認した。
同directoryの`retired-ui.json`に基準HEAD・patch hash・削除一覧を保持する。
Qt SDK・build用venv・残っていたMIG-008表示生成物を削除し、後者の最終reportは既存gzipとの一致を確認した。
Qt依存を含む古い`native/target/`は消去し、必要なcoreの検証用buildだけを作り直す。
Rust toolchain/依存cacheと現行GUIの`.venv/`は維持する。

削除後のRust workspace 153テスト、関連Python 76テスト、Rust Clippy/format、
Ruff lint/format、Markdown lint、厳格な翻訳検査、全9言語UIサイズ検証は成功。
残したmigrationテスト733件のcollection、文書リンクとworkflow YAML/runner参照も確認した。
追加の音声・性能・他OS試験とremote CI、commit/push/PR/Issue/Project更新は行っていない。

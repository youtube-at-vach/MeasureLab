# 次期コア検証の進捗

更新: 2026-10-04。主目的はMIG-008。Rust/QMLの採用は未決定。
工程・完了条件は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)を正本とする。
Windows・ARMはMIG-008後へ延期。長時間試験は現在の計画から削除した。

## 現在地

| 項目 | 状態 |
| --- | --- |
| 作業場所 | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`、macOS Intel |
| branch / 基点 | `codex/migration-filter-qt`、計画整理開始時のHEAD `1bc1e21c`。統合先は`codex/next-core-evaluation` |
| 参照 | `9fd79958`（MeasureLab 0.9.0）。元fixture・係数・許容差を維持 |
| main同期 | 最終確認は2026-10-03、`84013a76`をmerge `0fe41a7a`で取込み |
| Git状態 | 計画整理の開始時はremote一致・clean。filter/Qt接続は`28d5a390`、Native CI手動化は`1bc1e21c`へコミット済み |
| MIG-001〜003 | 環境・契約・参照fixtureを作成済み |
| MIG-004〜007 | Intelの両Qt、両backend入力、共有FFT/履歴/Timebase、表示/Trigger/校正、CSV/JSON、固定filterの評価結果をMIG-008へ再利用 |
| MIG-008 | Aの一つの2chフロー統合、Bの短い比較、Cの理由付き判断は未完了 |

004〜007の全tap、profile、他OS等の残項目をすべて完成させる前提は外した。
延期を検証済みとは扱わず、MIG-008の判断へ制約として添える。

## 次の作業

[008-A〜Cの実施順](../guide/RUST_QML_MIGRATION_PLAN.md#mig-008の実施順)に従い、まず008-Aへ直接進む。
CPAL / CXX-Qt / 2ch f32 / BlackHoleを主経路にし、
生成→固定route→取得/Timebase→波形/共有FFT→line/heatmap→基本校正→CSV/JSONを接続する。
不足する接続と、このフローを妨げる不具合だけを実装する。

008-Bは代表2ch条件の各30秒・1回と、core/表示編集の各1回を比較する。
長時間・全backend×全Qt×全言語×全chの反復、remote CI、別環境の準備は先行条件にしない。
全言語UIサイズはレイアウト・翻訳を変更した場合に確認する。

## 再開と検証

1. `git status --short --branch`、本書、変更対象のコードを確認する。
2. [native環境](../native/README.md#このworktreeで使う)で導入済みツールを有効にする。再導入・Hello world・全fixture再verifyは不要。
3. 008-Aの接続を実装し、変更した挙動のテストと代表フローを確認する。
4. 既存runnerのreportを利用し、結果・未確認点と次の作業を本書へ短く記録する。

関連手順は下表から必要なものだけ読む。環境の詳細は[参照環境](environment.md)。
新しい小変更ごとの手順書・決定記録、全source/binaryの複製や全artifact再監査は必須にしない。
Ruff lint/format、Markdown変更時のlintは[共通手順](../.agents/workflows/tool_usage.md)に従う。

## 再利用する証拠

既存の成功は記載条件の範囲だけを指す。MIG-008の統合・比較・採用判断の完了には置き換えない。

| 対象 | 結果と参照 |
| --- | --- |
| filter / 両Qt | 保存54実行、BlackHole24実行・48取得世代、raw回帰8実行成功。[手順](../native/filter-qt.md)、[決定0036](decisions/0036-filter-qt-integration.md) |
| f32→f64境界 | 保存30条件×5 pattern、native両backend6実行成功。[実装](../native/graph-core/src/filter.rs) |
| PortAudio callback | BlackHole2/4/8chでPortAudio/CPAL各6実行・18世代成功。[実装](../native/portaudio-input/src/lib.rs) |
| 共通input.raw | 保存32条件、PortAudio3実行とCPAL/両Qt6実行成功。[実装](../native/audio-core/src/backend.rs) |
| 表示/Trigger/校正/保存 | [表示](../native/live-display.md)、[Triggerの実装](../native/display-core/src/trigger.rs)、[校正](../native/calibration-edit.md)、[取得中保存](../native/qt-save.md)、[製品codec](../native/product-codec.md) |

最終結果と関連失敗のreport 25件は`.migration-local/evidence/`へgzipで保持した。
最新filter/Qtの5 reportはその`2026-10-03-filter-qt/`以下の
`saved-final-v2/report.json.gz`、`forward-final/report.json.gz`、`languages-final/report.json.gz`、
`live-final/report.json.gz`、`raw-trigger-final/report.json.gz`。
圧縮前後の内容一致を確認済み。対応表と元hashは`evidence/index.json`。
その時点のRust194件/関連Python304件と静的検査/UIサイズは成功。
途中の軸/replay/端点処理の失敗と修正は決定0036へ要約済み。

## 2026-10-04の整理

MIG-008の工程を統合・短い比較・判断へ集約した。
重複作業票/残工程表、詳細進捗履歴、完了済み試作の重複手順・決定記録と旧SDK記録を削除。
元文書はGit履歴`1bc1e21c`から取得できる。
古い中間アーティファクト445項目、重複source/binary/配布コピー、不要な検証用venvと生成物を削除した。
`.migration-local`は約75 GiBから約140 MiBへ縮小。独立rendererのbuildと導入時のsmoke/downloadも削除。
再開に使うQt SDK・toolchain・依存cache・主workspaceのbuild cacheは維持する。

旧report内のartifactパスとhashは当時の記録。対象の生データ・古い実行物は整理済みで再監査には使えない。
新たな比較は現在のコードと固定fixtureから実行する。
Native CIの二重のrunner実行を削除し、Qt実行を代表2chへ縮小。rendererは個別指定へ分離。

`.venv/`、`.tools/`、`.migration-local/`はGit管理外。
今回の計画整理では新たな音声/性能/他OS検証、push/PR/Issue/Project更新を行っていない。

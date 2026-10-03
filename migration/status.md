# 次期コア検証の進捗

更新: 2026-10-03。正本は[評価計画](../guide/RUST_QML_MIGRATION_PLAN.md)。Rust/QMLの採用は未決定。
現在はP0〜P2の評価中。MIG-008の完了と全41機能の移行完了は別に扱う。

このファイルは現状・残作業・再開の入口とする。過去の詳細な試験/失敗/証拠は
[2026-10-03までの詳細履歴](status-history-2026-10-03.md)へ移した（旧本文2,248行をそのまま保存）。
履歴内の「次は」「未コミット」は当時の記録。現在の判断には以下と[残工程表](remaining-to-mig008.md)を使う。

## 作業場所と基準

| 項目 | 現在の値 |
| --- | --- |
| macOS checkout | `/Users/vach/.codex/worktrees/next-core-evaluation/MeasureLab`（Codex管理、再利用） |
| 実行環境 | macOS 14.8.9 / Intel。Linuxの前回検証はUbuntu 26.04.1 / x86_64 |
| ブランチ | 統合先`codex/next-core-evaluation`、今回`codex/migration-backend-input` |
| 今回の開始点 | `144606b4`、remote一致・cleanの`codex/migration-filter-acquisition`から分岐 |
| 数値/DSP参照 | `9fd79958`（MeasureLab 0.9.0）。元fixture/係数/許容差を維持 |
| 最終main同期 | 2026-10-03、origin/main `84013a76`をmerge `0fe41a7a`で取込み。差分はCURRENT_DIRECTION.mdのみ |
| Git状態 | 前回のf64 filter取得接続は`144606b4`へコミット済み。今回の共通入力境界・文書整理は未コミット |
| 外部更新 | 今回のpush/PR/Issue/Project更新/公開配布は未実施。無人継続・定期通知は未設定 |

`.venv/`、`.tools/`、`.migration-local/`はGit管理外。worktreeを退役させる前に必要な証拠を保存する。
通常の音声回帰はBlackHole 16ch/2chを優先する。USB/物理clock/電圧/遅延の要件に限りUAC-232を使う。

## タスク

「検証済み」は記載範囲だけを指し、タスク全体やAC全体の合格を意味しない。

| タスク | 状態 | 検証済みの範囲 |
| --- | --- | --- |
| MIG-001 | 完了 | 分離worktree/環境/保存先、Rust/C++/Qt SDK、再開手順 |
| MIG-002 | 完了 | 41機能+共通10件、20プリミティブ、コア/数値契約、AC01〜16、比較protocolと作業票 |
| MIG-003 | 完了（参照側） | FFT24ケース、27契約/4保存例、filter21数値/6 rate境界。候補実装の採用判定とは別 |
| MIG-004 | 進行中 | Intel/Linuxの両Qt基本寿命、build/edit反復、ローカルpackage。ARM/Windows/clean環境とGitHub CIは残る |
| MIG-005 | 進行中 | N-channel input.raw queue/履歴/共有FFT、動的f32 route、短いUAC-232/BlackHole比較。今回、CPALとPortAudio評価workerの共通入力境界を追加 |
| MIG-006 | 進行中 | FFT/共有graph/履歴/Timebase/世代、pure filter、不変result/ID校正、v1/製品JSON・CSV/非同期保存/旧形式import。保存f64 filterの取得scheduler21ケース×5 chunkも検証済み |
| MIG-007 | 進行中 | 保存/BlackHoleの両Qt line/heatmap、分離/9言語、Trigger hold/retry/release、校正編集、v1/製品保存、製品import参照表。rendererはIntelの最小試験のみ |
| MIG-008 | 未着手 | 008-Aの同じ2chフロー統合、008-Bの同条件比較、008-Cの四案の理由付き判断が必要 |

既存の代表的な成果: 両Qt保存/製品importは4入力×9言語×両方式の72実行を各段階で検査。
BlackHole取得中保存はv1/製品の各2/4/8ch×両方式×3反復、計36実行を検査。
writerの250 ms待ち注入はbusy/取消/取得継続の診断で、実ディスク性能ではない。
詳細件数・失敗・artifact hashは[詳細履歴](status-history-2026-10-03.md)に保持した。

## 今回の変更と検証

[共通入力境界](../native/backend-input.md)と[決定0033](decisions/0033-common-backend-input.md)を追加した。
`InputBinding`/`InputWriter<T>`で実backend/device/精度/ID/port/rate/世代を固定し、
既存CPAL callbackとPortAudio評価workerを同じtyped queue/取得owner/共有FFTへ通す。
PortAudioはblocking入力worker→binary pipe経由。製品callback/Qtのbackend選択は未接続。
現行製品DSP/GUI、Cargo.lock、元fixture/係数/許容差は変更していない。

| 検証 | 結果・証拠 |
| --- | --- |
| 保存入力 | 4/8ch f32/f64×両backend binding×正逆port×boxcar/Hannの32条件成功。元bytes/共有FFT/全相対列/unknown/JSON・CSV/停止後pin・回収を照合 |
| 実PortAudio | BlackHoleの論理2/4/8chで3実行、各98,304 frame/96共有窓成功。元bytes/NumPy FFT/選択tone、overflow/statusなし、stream closeを確認 |
| CPAL/両Qt回帰 | BlackHole2/4/8ch×両方式の6実行成功。共有result/元bytes/寿命とstream回収を確認 |
| Rust/Python | workspace177件（新規3件）、関連Python116件と追加2件成功。新規境界45件を補強後に全件再検査 |
| 静的検査・参照verify | workspace Clippy/Rust fmt、Mypy116 source、Ruff lint/format696 files、Markdown lint234 files、台帳41件/20プリミティブ、diff check成功。FFT14/core4 FFT・27契約・4保存/filter21・6 rateのverify成功 |

最新reportは`.migration-local/2026-10-03-backend-input-final-v2/report.json`（result ID検査の補強後に全条件再取得・成功）。
source/binary/fixture/元bytes/全窓/出力hashとコマンドを保持し、比較前後のsource/binary一致を確認した。
CPAL reportは`.migration-local/2026-10-03-backend-input-cpal-qt/report.json`。
logの共通prefixは`2026-10-03-backend-input-`。Rust/Pythonは`workspace-final.log`/`python-final.log`、追加検査は`python-identity-final.log`。
`evidence-audit.json`で100 source/3実行物/343 artifact/18 logを照合。`source-snapshot/`と`binaries/`へ固定実体を保持した。
初回の保存比較は検証harnessのhistory status期待名で失敗し、修正後の32条件は成功。
途中のharness構文誤りも修正済み。Rust全体の初回はQt test実行物のframework探索で停止し、
`DYLD_FRAMEWORK_PATH`へ分離SDKを指定して再検査した。これらの失敗を合格には数えない。
レイアウト/翻訳の変更はなく、全体Pytest/全言語UIサイズ/GitHub CIは今回未実施。

実backendはf32。ローカルsounddeviceは`float64`指定を内部で`float32`へ変更するため、
実streamのdtype/rate/channel数を確認する。保存f64の成功をdevice f64対応の根拠にしない。
最初のfilter候補はf64因果3-tap `[0.25,0.5,0.25]`、48→24 kHzのまま。
実入力からの明示変換/来歴または対応精度の選択、filterのQt接続は次の単位で決める。

## 未完了と着手順

依存と完了条件の正本は[残工程表](remaining-to-mig008.md)、各再実行は[作業票](tasks.md)。
保存試験・現在のIntel/BlackHoleで進められる作業と、別環境/人の操作が必要な作業を分ける。

| 優先・作業 | 状態と次の具体的な作業 | 必要な条件 |
| --- | --- | --- |
| 1. 005-A-common | 入力境界の部分実装済み。PortAudioの製品callback/両Qt backend選択、動的route ack/世代、購読tapのgraph統合を進める | 保存入力/Intel/BlackHoleで着手可能 |
| 2. 006-Dの実入力/Qt接続 | 保存f64 scheduler済み。実backend f32との精度境界を明示して、一段filter/派生履歴/共有FFT/Trigger/保存を同じフローへ接続 | 現環境で着手可能。暗黙変換はしない |
| 3. 008-A統合 | 未着手。生成→明示route→取得/Timebase→波形/共有FFT→line/heatmap→基本V/FS校正→CSV/JSONを一つの2chフローへ統合。仮想4/8ch回帰とAC対応表を残す | 1〜2の対象backend/dtype/tapを固定する |
| 4. import/profile | import結果のline/heatmap/cursor/再保存、取得profileの再起動維持が未実装 | 現環境で独立して着手可能 |
| 5. 007-B/008-B性能 | 未着手。統合物を固定し、2/4/8chの30秒warmup+10分×3回、単独/複数view/保存/遅いGUI/負荷超過を同条件Pythonと比較 | 3の固定後。測定中に他build/GUI試験を走らせない |
| 6. 005-B/008-B音声 | 短い比較のみ済み。時刻写像/絶対遅延、排他/開始失敗/XRUN位置、USB/スリープ復帰/長時間が未確認 | 通常はBlackHole。物理試験には実機/配線、USB操作には人が必要 |
| 7. 004-B/008-B配布・操作 | Intel/Linuxの模擬probeは済み。実graph統合配布物、ARM/Windows/clean環境、window manager操作/High DPIは未確認 | 各実行環境と手動操作が必要 |
| 8. CI・証拠整理 | 今回の保存比較/拒否テストもNative CIへ追加済み。Linux ICU修正後と新規比較のremote実行は未確認 | 対象変更の公開時にcommitとCI結果を照合 |
| 9. 008-C判断 | 未着手。AC01〜16の証拠/未達、性能/反復/実機/配布/保守費用を四案へ集約 | 材料が揃った時点で理由/未確認/次の範囲/再評価条件を記録 |

残るtapは`input.calibrated`、`output.mixed/post_dut/device_buffer`。結果への後段ID校正を
input.calibrated tapの実装と混同しない。DUT未実装をmixed/post_dutの同一tap扱いにしない。
f32 filter/chain/SOS gap回復、全校正map/SPL、外部Trigger実機adapter、全機器保証も未実装/未確認。
rendererはwgpu候補約29〜30 Hz、基準100万点のJSON/QML境界はSIGBUSを3回再現。
採用・個別widget実装・native GPU texture共有の合格には使わない。

## 次の作業と再開

1. `git status --short --branch`とこのファイルを確認し、未コミット変更を保護する。
2. [環境手順](environment.md)と[native環境](../native/README.md#このworktreeで使う)で参照版/保存先/ツールを確認する。
3. [作業票のverify手順](tasks.md)で既存FFT/core/filterを検査する。期待値/許容差を変更せず、別環境だけ`--portable`を明示する。
4. 上の優先1〜2から008-Aへ進める。独立probeの成功だけで統合・性能・他OSを完了にしない。
5. 結果/失敗/未実施とreport/hashを記録する。新しい詳細は専用手順/決定/reportへ置き、このファイルは現状と次の作業に絞る。

共通入力の再実行:

```bash
./.venv/bin/python scripts/migration_backend_input.py --output .migration-local/backend-input-new
./.venv/bin/python scripts/migration_backend_input.py --virtual-device --output .migration-local/backend-input-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_backend_input.py
```

## 証拠と履歴の入口

| 対象 | 参照先 |
| --- | --- |
| 今回の共通入力 | [手順](../native/backend-input.md)、[決定0033](decisions/0033-common-backend-input.md)、上記最新report |
| 保存f64 filter取得 | [手順](../native/filter-acquisition.md)、[詳細結果](status-history-2026-10-03.md#mig-006-d-integration-保存f64のfilter取得scheduler) |
| 両Qt/取得中保存 | [Qt保存](../native/qt-save.md)、[取得中保存](../native/live-save.md)、[詳細履歴](status-history-2026-10-03.md) |
| 製品互換/import | [native codec](../native/product-codec.md)、[native import](../native/product-import.md)、[Qt import](../native/qt-import.md) |
| 過去の全試験/失敗/hash | [詳細履歴](status-history-2026-10-03.md)。元本文SHA-256 `099ed2ae6ec57c11a77c0073896c12ac9520ac3e5934ba4cc9fb5b014f577a62` |
| Linux/別環境の再開 | [環境手順](environment.md#linuxでの再開)、[比較protocol](benchmarks/protocol.md) |

## mainとの同期・変更の統合

週1回と各段階の終了時を目安に、変更を保護してfetch/diff/mergeする。[評価計画の運用ルール](../guide/RUST_QML_MIGRATION_PLAN.md)を参照。
共有長期branchは通常rebaseしない。同期時は競合解消だけでなく台帳/参照/fixture/契約を照合し、対象テスト/Ruffと取込commitを記録する。
独立変更は`codex/migration-<task>`へ分岐し、PRの比較先は`codex/next-core-evaluation`。
PR依頼時は[CI Pre-checker](../.agents/skills/ci-prechecker/SKILL.md)を実施し、Ready for reviewで作成する。プレビューは安定版更新へ接続しない。

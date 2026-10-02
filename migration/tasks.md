# MIG-002後の実行単位

2026-10-02更新。Issue作成や技術採用の決定ではなく、このworktreeで再開するためのローカル作業票。
共通基準は`9fd79958f6a8bbae6808813d3704617612e6d26c`と[決定0001](decisions/0001-p0-contracts.md)。
各タスクは着手時にbranch/commit、変更境界、コマンド、結果、未確認点を[status](status.md)へ追記する。
既存の検証ブランチを使い、独立した実装を切り出すときは`codex/migration-<task>`、PR比較先は`codex/next-core-evaluation`。

## MIG-002の内訳

| 子タスク | 成果 | 状態 |
| --- | --- | --- |
| 002-A | [41機能+共通10件の台帳](inventory.md)、現行source/test、状態とプリミティブ対応 | 完了 |
| 002-B | [20プリミティブ](primitives.md)、入出力/単位/状態/時刻/精度/validity/共有、逆引き | 完了 |
| 002-C | [コア契約](contracts/core.md)、[数値基準](contracts/numerics.md)、現行との既知差 | 完了 |
| 002-D | [AC01〜16](contracts/acceptance.md)、[性能/反復予算](benchmarks/protocol.md)、後続作業票 | 完了 |

完了はP0成果物の作成・整合確認を意味する。fixture比較や候補実装が完了した意味ではない。

## 次に実装する単位

| ID | 目的・範囲 | 依存・変更境界 | 完了条件・検証 | 今回含めないもの | 状態 |
| --- | --- | --- | --- | --- | --- |
| 003-A | GUIなしの参照runner、manifest/hash、理論付きFFT/窓/RMS/endpoint | 002、P04/P05。migration fixtureとscripts/testsだけ、現行DSPは変更しない | AC01/04。基準source hash、同じ入力で再生成/再検査、破損hash・違う版・shapeを拒否。現行値と理論値と既知差を別保存 | 候補Rust実装、製品FFT修正 | 完了（2026-09-30、参照側20ケース） |
| 003-B | 仮想4/8ch、route、trigger/history、gap/世代、校正/保存metadataのoracle | 003-A、P02/P03/P13/P14。core.mdの意味をfixtureへ | AC02/03/08/09/11/12。厳密なID/位置/reasonと独立した手計算例。Python旧engineにない能力は新契約oracleと明記 | 物理I/O、共有graph本体 | 完了（2026-09-30、4 FFT・27契約例・4保存例。実バッファは006-C） |
| 003-C | 最小FIR/rate写像、現行polyphase/代表SOS参照 | 003-A、P06。数値契約と係数・初期条件固定 | AC10/14。理論有限和、impulse、DC、tone、gap、chunk分割一致。旧版のinvalid rate挙動を別記録 | 製品用resampler選定、全rate構成 | 完了（2026-09-30、21数値ケース・6 rate境界。参照側のみ） |
| 004-A | Qt SDKを分離導入・版固定し、CXX-Qt/Qt Bridgeで同じ小画面 | 002-C/D。native内の薄いQt境界。導入前に現在の公式要件を確認 | Start/Stop、worker通知、list model、再生成/破棄、遅い通知、AC07/13。両方式の実行物と差分表 | 本格採用、41画面 | 完了（2026-09-30、Intel・模擬GUI境界。AC07/13の実graph/音声部分は後続） |
| 004-B | 上記のbuild/QML編集/packageと対象OS起動比較 | 004-A。同一workload/依存組合せとbenchmark記録 | AC16と性能protocol。Intel/ARM/Windows/Linuxの実行済み・未実行を分離 | 未所有環境の成功扱い、安定版配布 | Intel範囲完了（2026-09-30）。その他OS/clean環境、修正後Linux CIは未確認 |
| 005-A | N-channel buffer/route/tap、backend共通境界 | 003-A/B。P02/P03。PortAudio基準とCPAL比較 | AC01〜03/09/11。4/8ch・非対称I/O・明示mapping・queue overflow。Rust追加時は独立CI追加 | network多ch拡張、全機器 | 進行中（2026-10-01、取得graphと動的f32 route mailboxを接続。保存12条件とCPAL/BlackHole配送を検査。全tap・PortAudio共通adapterは後続） |
| 005-B | 仮想I/O回帰と必要時の実機2ch、XRUN/再接続、排他/停止/時刻 | 005-A。通常はBlackHole 16ch／2ch、物理要件だけUAC-232。device/配線/校正を記録 | AC11/13/16、同じ配線で現行と交互測定。測定前に許容振幅差/遅延誤差を決める | 実機4/8/16ch保証 | 進行中（2026-10-01、BlackHoleの静的比較/実取得graphにCPAL動的routeの9取得・3保留cancelを追加。切断復帰・排他・絶対遅延/長時間は未確認） |
| 006-A | FFT/窓/単位/PSDを参照比較 | 003-A、P04/P05。GUI非依存core | AC01/04、f32/f64・非2冪/極大・endpoint。必須数値条件合格、core編集時間記録 | 全解析モジュール | 完了（2026-09-30、保存コーパス24件とIntel編集5回。全体採用・他OS・Python相対比較は未確認） |
| 006-B | 固定DAG・共有key・購読token・bounded cache | 006-A、003-B、P15 | AC05〜07。評価count/同一ID、条件分岐、独立平均、最後の解除/終了回収 | 汎用graph editor | 完了（2026-09-30、pure graphのRust16テスト/保存18ケース。実取得/Qt統合は後続） |
| 006-C | trigger/history・Timebase・generation・validity | 003-B、006-B、P03 | AC08/09、異なるcursor/通知遅延・保持超過・旧世代拒否。共有graphへ統合 | 外部trigger実機adapter | 完了（2026-09-30、worker所有履歴/pure graph・保存13契約/4入力bytes、Rust27テスト。実取得/Qtは後続） |
| 006-D | 最小rate変換/filterとvalidity伝播 | 003-C、006-C、P06 | AC10/14、同じgraph内で遅延/区間/phase stateを保持 | 高品質resamplerの全機能 | 完了（2026-09-30、f64保存21ケース×5 chunk/6 rate境界と一段のpure graph。f32・IIR gap回復・実取得/Qtは後続） |
| 006-E | 不変result・channel校正・CSV/JSON来歴 | 003-B、006-B/C、P13/P14 | AC12、再読込、保存失敗、profile変更後の不変性、uncalibrated | 旧設定の自動移行 | 完了（2026-10-01、pure不変result/ID校正/JSON・CSV。保存2契約・4例と4/8ch f32/f64。非同期workerは次行、製品互換/Qt保存操作は後続） |
| 006-E-async-save | 不変snapshotのbounded非同期保存worker | 006-E、007-A-calibration-editのencode負荷記録。graph-core/exportと独立runner | AC07/12/13のworker境界。受付/実完了/失敗/pending cancel/寿命、graph進行、2契約と4入力の両format完全往復 | Qt保存操作、製品互換形式、pair transaction、取得中/長時間性能 | 評価範囲完了（2026-10-02、Rust新規9件、保存12実行/36 saved/36 failed）。結果はstatus |
| 006-E-compat | 製品形式/旧CSV・JSONとsnapshotの互換adapter・読込み | 006-E、006-E-async-save、現行ExportTrace。製品版管理は008で判断 | AC12。元値/軸/単位/校正/metadata、旧fileのunknown、失敗/上書きの保証範囲を検査 | 全旧設定自動移行、全解析形式 | 評価用Python adapterを追加（2026-10-02）。製品JSON carrier/CSV sidecarとnative readerの完全往復、旧fileのunknownを検査。native snapshot codec/file workerは次行。Qt製品保存formatは007-A-product-save、native読込みは006-E-native-importへ追加。Qt import操作と取得profile再起動維持は後続 |
| 006-E-native-product | 製品snapshot codecと共通非同期保存worker | 006-E-compat、006-E-async-save、実ExportTrace/exporter | AC12の全値/元精度/来歴、双方向往復、receipt、上書き拒否、部分pairと失敗後の復帰。worker寿命と既存Qt回帰 | Qt製品import、旧fileのnativeトレースimport、取得profile再起動維持、取得中性能/他OS | 保存fixture範囲完了（2026-10-02、12実行/72双方向完全往復、48 saved/48期待failed）。Rust新規7件と既存Qt経路も成功。詳細と証拠はstatus。006-E全体は未完了 |
| 006-E-native-import | 旧トレース/完全snapshotのnative製品読込み | 006-E-compat、006-E-native-product。product parser/独立CLI/実exporter | AC12。旧JSON/CSV 32条件/sidecar、unknown、全snapshotの3入口完全一致、破損拒否、入力不変 | Qt非同期import/表示/取消/寿命、取得profile再起動維持、負荷/他OS | 保存fixture範囲完了（2026-10-02、旧JSON/CSV32条件・旧pairと18完全import、Rust新規8件/対象Python新規75件）。詳細はstatus。同期file-worker APIのみ |
| 007-A | 同じ結果をline/heatmapへ表示、操作/画像保存 | 004、006。P19のsnapshot境界 | AC05/07/08、軸/cursor/zoom・画像・再生成・サイズ/9言語 | 全41機能のUI | 進行中（2026-10-01、保存4/8ch f32/f64とBlackHole実入力→実graph→両Qt表示。分離view/翻訳JSON/9言語に手動Triggerのhold/retry/releaseを追加。セッションID校正は007-A-calibration-input、取得中のQt編集・適用は007-A-calibration-editへ追加。製品保存は007-A-product-saveへ接続。製品import/実window manager/他OSは後続。実施結果はstatus） |
| 007-A-trigger | 取得履歴の非消費query→共有raw FFT→trigger付き不変result | 005-graph、006-C/E。解析owner APIと独立runner | AC08/09のpending/gap/分数残差/旧世代拒否、通常平均/位置不変、保存4入力×2bindingの全bytes・32完全result | Qt操作、実入力要求配送、arm/cancel/検出器、長時間性能 | worker範囲完了（2026-10-01）。Qt/実入力の配送は次行で検証 |
| 007-A-trigger-display | Qtのtyped要求/revision→解析owner、両view共通hold/retry/release | 007-A-trigger、007-live-display/分離/翻訳境界 | AC08/09/13。保存4入力×9言語×両Qt、元bytes/全result、pending/gap非数値、保持中の取得継続、旧世代/停止/破棄、BlackHole短時間診断 | 検出器のarm/cancel、前段filter/外部clock、製品校正/保存、長時間性能/他OS | 配送を追加（2026-10-01）。成功件数と未確認範囲はstatus |
| 007-A-calibration-input | session ID/device/port校正→通常/Trigger取得結果→両QtのV/dBVとv1診断保存 | 006-E、007-A-trigger-display。後段校正/同じ不変resultを使用 | AC12/13。port/profile逆順、異なる係数/disabled/未指定、元bytesの全配列、完全CSV/JSON再読込、寿命/9言語/サイズ、BlackHole短時間診断 | Qtのprofile編集・適用mailbox、製品保存UI/互換/async、SPL/map、物理校正/性能/他OS | 接続範囲完了（2026-10-02、保存72実行/BlackHole18実行）。詳細と未確認範囲はstatus |
| 007-A-calibration-edit | 取得中のQt profile編集・適用と通常/Trigger結果 | 007-A-calibration-input。typed mailbox/解析ownerと共通ダイアログ | AC12/13。原子的拒否/世代/busy/停止、変更前後の全配列/元bytes/共有raw/旧保持結果、CSV/9言語/サイズ、BlackHole短時間 | 製品保存UI/互換/async/再起動維持、SPL/map、物理校正/性能/他OS | 評価範囲完了（2026-10-02、保存72実行/BlackHole18実行、既存live回帰6実行）。詳細と未確認範囲はstatus |
| 007-A-save | 両Qtから同じ通常/Trigger snapshotの保存操作 | 007-A-calibration-edit、006-E-async-save。display-core/両Qt/共通QML | AC07/12/13。受付と実完了、busy/cancel/失敗でも取得継続、hold/分離/再生成、全値/来歴/9言語/サイズ、GUI外のjoin | 全旧形式、長時間性能/他OS | 保存fixture範囲完了（2026-10-02、4入力×9言語×両Qtの72実行）。v1通常/Trigger resultのpin、受付/実完了/失敗復帰、GUI外の終了を検査。製品format接続は次行。BlackHole保存操作/性能は後続。詳細はstatus |
| 007-A-product-save | 両Qt保存操作へ製品JSON/CSVを接続 | 007-A-save、006-E-native-product。共通display-core/worker/QML | AC07/12/13。旧pin/校正/全配列の完全往復、同じ容量/操作ID、CSV/sidecar両公開と部分失敗、9言語/サイズ、GUI外の終了 | 製品import UI/旧トレースnative import、再起動校正維持、取得中性能/他OS | 保存fixture範囲完了（2026-10-02、4入力×9言語×両Qtの72実行、497 saved/216期待failed/151取消、216元bytes oracle結果）。検査結果と証拠はstatus。MIG-007/008全体は未完了 |
| 007-B | 描画/GUI遅延・CPU/RSS・表示編集時間 | 007-A、性能protocol | AC15/16。遅いGUIでも測定を保ち、単独/複数表示を比較 | 理論だけでの性能判定 | 未着手 |
| 007-C | Plot Renderer Feasibility Spike。簡易plotterを基準にrsplot / wgpu系など1〜2候補を最小試験 | 004、007-Aの既存表示境界。独立試験コードと検証記録。007-A全体の完了は待たない | Spectrum 10万〜100万点の連続更新、Spectrogram rolling image、Zoom/Pan・座標変換・カーソル、QML統合/ライフサイクル、CPU/GPU負荷/コピー回数の比較表と再実行手順・未確認点 | renderer採用判断、製品組込み、個別widgetの本実装 | Intel最小試験・記録完了（2026-10-01、wgpu 1候補/PyQt画像provider。基準100万点はSIGBUS。native texture共有・他OS等は未確認） |
| 008 | 2chフロー統合と四案の比較判断表 | 004〜007、実機/配布記録 | AC01〜16、仮想4/8ch回帰、採用/変更/段階導入/現行継続の理由と未確認点 | P3以降の自動開始、旧版置換 | 未着手。008-A統合→008-B比較→008-C判断。依存と残工程は下の整理表 |

MIG-003はA/B/Cすべての入力/期待値と再現コマンドが揃うまで完了にしない。
MIG-004はSDK導入だけで完了にしない。OSや実機の不足はその試験だけを未確認として残し、
依存しないfixture/純粋演算/GUI境界の検証は進められる。
各試験の具体的な実行コマンドは実装と同時に作業票へ追加し、まだ存在しないrunnerを実行済みと記録しない。
007-Cの試験条件・完了成果物は[評価計画の簡易検証タスク](../guide/RUST_QML_MIGRATION_PLAN.md#121-mig-007-c-plot-renderer-feasibility-spike採用判断ではない)を参照する。
007-Cの[再実行・負荷/コピーの境界](../native/renderer-spike.md)と[試験結果](status.md#mig-007-c-plot-renderer-feasibility-spikeの成果と検証)を追加済み。基準100万点の失敗も比較記録へ残す。

[MIG-008までの残工程](remaining-to-mig008.md)に、未完了範囲・実施順・依存・実機/別環境の必要条件を整理した。
007-A-saveの保存fixture範囲を進めた。006-E-native-productの保存fixture範囲を追加。Qt製品format接続を007-A-product-saveへ追加。旧トレースと完全snapshotのnative importを006-E-native-importへ追加。次はQt製品import、005-A-commonへ進める。006-D-integration、008-A/B/Cも同表のローカル作業単位であり、Issue作成や採用判断は行っていない。

## 003-Aの再検査

[fixture仕様・生成/再検査手順](fixtures/README.md)と[決定0002](decisions/0002-fft-reference-runner.md)を参照。
通常の検査は保存bytesを読むだけで、期待値の再生成と分離する。

```bash
./.venv/bin/python scripts/migration_fft_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_reference.py
./.venv/bin/python scripts/migration_fft_reference.py verify --fixtures .migration-local/fft-extended-v1 --baseline migration/fixtures/fft-extended-v1.manifest.json
```

AC01の4/8ch参照fixtureは003-Bで作成済み。候補実装のAC01/04合格は005/006以降。

## 003-Bの再検査

[fixture仕様](fixtures/core-v1.md)と[決定0003](decisions/0003-core-contract-oracles.md)を参照。
新契約モデル・手計算期待値・現行FFTの由来を分けて保存し、通常の検査ではfixtureを更新しない。

```bash
./.venv/bin/python scripts/migration_core_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_core_reference.py
```

003-Bの履歴oracleは区間の可用性まで。005/006では実際の候補coreへ同じ入力を通し、
波形snapshotの保持・所有権・購読を追加検証する。

## 003-Cの再検査

[fixture仕様](fixtures/filter-v1.md)と[決定0004](decisions/0004-filter-rate-reference.md)を参照。
FIRは新契約モデル、polyphase/SOSは現行参照と独立有限和・差分方程式を区別する。
同じ入力・係数・初期条件・端点を固定し、通常verifyは期待値を書き換えない。

```bash
./.venv/bin/python scripts/migration_filter_reference.py verify
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_reference.py
```

003-A/B/Cの保存入力・期待値と再現検査が揃い、MIG-003は参照側として完了。
004-AでQt開発SDKと両実行物を固定し、Intelで基本GUI境界を比較した。
004-BでIntelの反復build/編集/ローカルpackageを検証した。他OS/clean環境は未確認。
AC07の実graph所有権は006-B、実音声回収は005-B/008。
005-A、006-Aの参照側の依存が揃った。006-Aへ純粋FFT候補と同じfixture比較、Rust CIを追加した。
MIG-006-Dでは一括APIをchunkごとに再起動せず、state/phase/validityをgraph内で保持する。

## 004-Aの再検査

[起動手順](../native/qt-probe.md)の環境変数を設定し、[共通プローブ](../native/qml/Main.qml)を実行する。
[決定0005](decisions/0005-qt-boundary-probes.md)で、模擬worker・Qtの寿命検査と実graph/実音声の合格を分ける。

```bash
cargo +1.98.1 build --locked --manifest-path native/Cargo.toml
cargo +1.98.1 fmt --manifest-path native/Cargo.toml --all --check
cargo +1.98.1 test --locked --manifest-path native/Cargo.toml -p probe-core
cargo +1.98.1 clippy --locked --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
./.venv/bin/python scripts/migration_qt_probe.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --report .migration-local/qt-probe.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_probe.py
```

通常runnerは保存fixtureを書き換えない。時間は短い診断試行として記録し、004-Bの性能protocolに代用しない。

## 004-Bの再検査

[反復測定手順](../native/qt-iteration.md)に従い、作業用コピーで固定した表示変更を繰り返す。
runnerはRust/SDK環境を設定し、依存取得と製品sourceの変更を行わない。

```bash
./.venv/bin/python scripts/migration_qt_iteration.py --qt-prefix .tools/qt/6.11.2/macos --report .migration-local/004-b.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_iteration.py tests/logic_verification/test_migration_qt_probe.py
```

clean 3回、no-op warmup1回+5回、QML編集5回、package3回を方式ごとに実行する。
`--smoke`は診断用で、性能protocolの完了にしない。
ローカルZIP展開起動、クリーンOS/配布、他OS/CPUを別扱いにする。
005-A/006-Aは残るOS検証を待たずに進められるが、004-Bの不足をその合格に置き換えない。
[比較記録](decisions/0006-qt-iteration-local-bundles.md)に条件・結果・限界を要約している。
全sampleはローカルの`benchmarks/results/2026-09-30-004-b-intel.json`へ保持し、Git管理外に置く。

## 006-Aの再検査

[純粋FFTの手順](../native/fft-candidate.md)と[決定0007](decisions/0007-pure-fft-candidate.md)を参照。
候補実行物へ003-A/Bの元の入力bytesを通し、保存済み理論/現行の両方と比較する。
Qt SDKや実機は不要。拡張6件はローカル配列とversioned manifestの一致を要求する。

```bash
./.venv/bin/python scripts/migration_fft_candidate.py --extended .migration-local/fft-extended-v1 --report .migration-local/006-a-verify.json
./.venv/bin/python scripts/migration_fft_iteration.py --extended .migration-local/fft-extended-v1 --report .migration-local/006-a-edits.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_fft_candidate.py
```

反復中は他のbuild/testを止める。通常の比較はfixtureを書き換えない。
006-Bのpure共有graphは完了。005-Aのpure音声buffer/routeとCPAL adapter、005-Bの短い実機比較を追加した。
006-Cのworker所有履歴/Timebase写像はpure graphへ接続済み。実取得/graph統合・物理clock写像・動的route配送は後続。

## 006-Bの再検査

[共有graphの手順](../native/shared-graph.md)と[決定0008](decisions/0008-shared-fft-graph.md)を参照。
元の入力bytesで同じFFT結果を2購読へ渡し、数値・評価回数・結果ID・Source・終了時回収を検査する。
Graphは制御/解析worker用API。取得queue/永続scheduler/音声callback/Qt adapterは後続で接続する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
./.venv/bin/python scripts/migration_graph_candidate.py --report .migration-local/006-b-verify.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_graph_candidate.py
```

006-C/D/Eのpure境界を検証済み。005-A/Bの取得/graph接続または007-Aの実result表示境界へ進められる。Rust/QML採用・AC07の実音声/GUI/保存統合の合格とは分ける。

## 005-A/Bの再検査

2026-09-30のユーザー指示で、通常のdeviceテストはBlackHole 16ch／2chを優先する。
UAC-232は物理I/O、USB切断／復帰、校正・配線、物理遅延など実機が必要な要件だけに使う。
[決定0010](decisions/0010-blackhole-virtual-audio.md)と[環境の引き継ぎ](environment.md#音声テストの引き継ぎ)を参照。

[音声境界と実機手順](../native/audio-boundary.md)と[決定0009](decisions/0009-audio-boundary-uac232.md)を参照。
通常の保存比較はdeviceを開かない。実機runnerは新しい出力ディレクトリと明示的なhardware指定を要求する。

```bash
./.venv/bin/python scripts/migration_audio_candidate.py --report .migration-local/005-a-new.json
./.venv/bin/python scripts/migration_audio_virtual.py --virtual-device --output .migration-local/blackhole-new-run
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_candidate.py tests/logic_verification/test_migration_audio_virtual.py
```

005-Aはpure境界とCPAL基本adapter、005-Bは短い実機2ch／仮想2・16ch診断まで。
4／8ch routeは16portへ明示mappingする。2chは現行AudioEngine、16chは直接PortAudioとの比較。
input.rawのqueue/履歴/共有FFTは005の[取得worker](../native/acquisition-candidate.md)で接続した。
動的f32 routeのcallback配送は005の[mailbox候補](../native/dynamic-route.md)で追加した。
全tap、製品N-channel共通adapter、device/host時刻写像、Qt統合は未実装。
USBは今回は接続したまま。出力Rの配線、切断/復帰、device排他、時刻写像、長時間と実graph統合は未確認。
006-Cのpure履歴/Timebaseはこれらを待たずに検証済み。実取得/graph接続は残る。

追加の取得graph検査:

```bash
./.venv/bin/python scripts/migration_audio_graph.py --report .migration-local/005-graph-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_graph.py
```

保存4/8ch f32/f64をidentity/逆順bindingで通す。実BlackHoleの同じrunnerもgraph件数・共有・回収を検査する。

追加の動的出力route検査:

```bash
./.venv/bin/python scripts/migration_audio_route.py --report .migration-local/005-route-new.json
./.venv/bin/python scripts/migration_audio_route.py --virtual-device --output .migration-local/005-route-blackhole-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_route.py
```

保存4/8ch f32の12条件で値/区間/要求/実位置/revisionとmixed/device bytesを検査する。
BlackHoleは2→2/4→16/8→16を各3回とPreparing保留cancel。PortAudio動的比較・全tap・Qt/長時間は後続。

## 006-Cの再検査

[履歴/Timebaseの手順](../native/history-candidate.md)と[決定0011](decisions/0011-history-timebase-graph.md)を参照。
003-Bの保存履歴/時刻13契約と4/8ch f32/f64の元bytesを実履歴へ通し、共有FFTへ渡す。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
./.venv/bin/python scripts/migration_history_candidate.py --report .migration-local/006-c-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_history_candidate.py
```

独立reader・遅い通知・保持超過・gap/pending・世代fence・validity・正確な時刻を検査する。
006-Dのfilter/rateと006-Eの基本校正/保存もpure境界を検証済み。実取得/Qt/物理clock/永続schedulerは後続。

## 006-Dの再検査

[filter/rateの手順](../native/filter-candidate.md)と[決定0012](decisions/0012-filter-rate-graph.md)を参照。
保存21ケースを5種類のchunkで通し、理論/現行数値、phase/state、delay/trigger、validityと共有FFTを検査する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
./.venv/bin/python scripts/migration_filter_candidate.py --report .migration-local/006-d-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_candidate.py
```

NumPy-only CIは明示`--portable`を使う。原点/処理遅延のunknownを0へ補わず、係数bitsとfixtureを固定する。
006-Eの基本校正/保存もpure境界を検証済み。IIR gap回復、f32、chain、実取得/Qt/永続scheduler/物理clockは後続。

## 006-Eの再検査

[校正/保存の手順](../native/result-candidate.md)と[決定0013](decisions/0013-result-calibration-exchange.md)を参照。
保存2校正契約/4交換例と4/8ch f32/f64の元bytesを不変resultへ通す。

```bash
./.venv/bin/python scripts/migration_result_candidate.py --report .migration-local/006-e-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_result_candidate.py
```

ID校正・profile/世代変更後の不変性、未校正、null/reason、軸/Timebase/trigger、完全再読込と保存失敗を検査する。
NumPy-only CIは明示`--portable`。製品importer/Qt保存操作/取得中の保存負荷/校正mapは後続。

## 006-E 非同期snapshot保存の再検査

[非同期保存手順](../native/async-save.md)と[決定0024](decisions/0024-async-snapshot-save.md)を参照。
既存v1形式を使い、元fixture/許容差を変更せず、両formatの完全往復と実workerのreceiptを検査する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core --lib export::tests
./.venv/bin/python scripts/migration_result_candidate.py --async-save --output .migration-local/async-save-new --report .migration-local/async-save-new/report.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_async_save_candidate.py tests/logic_verification/test_migration_result_candidate.py
```

新規directoryに12実行/36 saved/36 failedと全file/hashを保存する。別OS/最小環境は明示`--portable`。
workerはbounded job数/完了/失敗/pending cancel/寿命の範囲まで。
両Qtのv1操作と[native製品snapshot codec/worker](../native/product-codec.md)は別単位で追加した。
Qt製品format接続、byte予算/取得中の負荷/長時間/他OSは後続。

## 006-E 製品互換adapterの再検査

[互換手順](../native/product-exchange.md)と[決定0025](decisions/0025-product-exchange-compatibility.md)を参照。
現行ExportTrace/exporterを使う評価用Python adapter。製品schemaの確定やGUI import操作ではない。

```bash
./.venv/bin/python scripts/migration_product_candidate.py --output .migration-local/product-compat-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_product_candidate.py tests/logic_verification/test_migration_result_candidate.py tests/core/export/test_json_exporter.py tests/core/export/test_csv_exporter.py
```

2校正契約/4交換例と4/8ch f32/f64のJSON/CSV両入口から12実行/24完全snapshot往復を検査する。
旧JSON/CSVの値/軸/単位/校正/metadataを保持し、旧取得情報はunknown。
merged CSVの補間は元gridの復元にしない。完全CSV復元はindependent列とmetadata sidecarが必要。
native codec/保存workerは[専用手順](../native/product-codec.md)で追加し、runnerの`--native-product`で再検査する。
Qt製品format接続/取得profile再起動維持、pair transaction、取得中性能/他OSは後続。

## 006-E native製品importの再検査

[手順](../native/product-import.md)と[決定0029](decisions/0029-native-product-import.md)を参照。

```bash
./.venv/bin/python scripts/migration_product_import_candidate.py --output .migration-local/native-import-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_product_import_candidate.py
```

別OS/NumPy-only CIは明示`--portable`を追加する。旧JSON/CSVのunknownと、完全snapshotを区別する。
Qtの非同期配送/表示/寿命、再起動取得profile、負荷/長時間/他OSは後続。

## 007-Aの再検査

[表示境界の手順](../native/display-candidate.md)と[決定0016](decisions/0016-shared-result-display.md)を参照。
Qt環境を設定し、003-Bの保存入力を実取得queue/履歴/FFTへ通す。004-Aの模擬workerとは別の実行物。

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core
./.venv/bin/python scripts/migration_qt_display.py --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-display-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_display.py
```

4/8ch f32/f64 × 両方式。同一result/区間/Timebase、実graphの共有・購読解除、cursor/zoom、
遅いGUI・旧世代拒否・再生成・PNG・動作中終了を検査する。全peak配列/軸を既存期待値へ照合する。
新しい出力先を指定し、元fixtureと既存runを上書きしない。NumPy-only CIは明示`--portable`を使う。
保存replayと英語QMLの初期境界まで。BlackHole実入力は[追加手順](../native/live-display.md)へ分離した。
trigger UI/校正・製品保存操作/長時間性能/他OSは後続。分離表示/9言語は下の追加検査を使う。

```bash
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_live.py
```

分離Windowと9言語の追加検査は[手順](../native/workspace-display.md)と[決定0018](decisions/0018-detached-localized-displays.md)を参照する。

```bash
./.venv/bin/python scripts/migration_qt_workspace.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-workspace-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_workspace.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_live.py
./.venv/bin/python scripts/check_trn_keys.py --strict
./.venv/bin/python scripts/check_ui_size_limits.py
```

既定は最大8ch f64×9言語×両方式、`--all-inputs`は4/8ch f32/f64を含む。
同じview/tokenの分離・再接続、native close/最後の解除、再オープン、分離中の再生成/終了と3画像を検査する。
Qt SDK/offscreenの結果で、実window manager/他OS/font/DPI、動的言語変更や製品41画面の移植は含めない。
BlackHole回帰は他のGUI/renderer/build試験が終わってから実行する。負荷中の取得gapも失敗記録に残す。

Trigger captureの解析owner接続は[手順](../native/trigger-capture.md)と[決定0020](decisions/0020-trigger-capture-worker.md)を参照する。

```bash
./.venv/bin/python scripts/migration_trigger_candidate.py --output .migration-local/007-trigger-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_trigger_candidate.py
```

保存4/8ch f32/f64×2binding、未取得/遅い通知/1frameずれ/同じraw共有/保持超過/旧世代/stop後の不変性を検査する。
N≤4096の同期worker APIまで。Qtからの配送は[追加手順](../native/trigger-display.md)で検査する。

```bash
./.venv/bin/python scripts/migration_qt_trigger.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-trigger-display-new
./.venv/bin/python scripts/migration_qt_trigger.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-trigger-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_trigger.py
```

保存4入力×9言語×両Qt、pending/明示retry/共有hold/分離/解除/世代/停止/破棄、全result/bytesとPNGを検査する。
BlackHoleは他のGUI/build試験を止めて実施し、元取得bytesから全配列を独立計算する。長時間/負荷下/他OSは後続。

## 007-A セッションID校正の再検査

[取得/Qt校正の手順](../native/calibration-display.md)と[決定0022](decisions/0022-session-calibration-display.md)を参照。

```bash
./.venv/bin/python scripts/migration_qt_calibration.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-calibration-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_live.py
```

保存4/8ch f32/f64×9言語×両Qt。通常/Triggerの全result、相対/絶対配列、
ChannelId/device/port/実区間/revision、未校正、CSV/JSON、保持/再開/破棄、実ラベル/非切詰め/サイズを検査する。

```bash
./.venv/bin/python scripts/migration_qt_calibration.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-calibration-live-new
```

BlackHoleの診断係数は物理校正の証拠ではない。元取得bytesから全数値を照合する。
Qtのprofile編集・適用は[次の検証単位](../native/calibration-edit.md)で追加・検査した。
製品保存操作/互換/非同期化、物理校正/期限/map、長時間/性能/他OSは後続。

## 007-A Qt校正profile編集・適用の再検査

[編集・適用の手順](../native/calibration-edit.md)と[決定0023](decisions/0023-qt-calibration-edit.md)を参照。

```bash
./.venv/bin/python scripts/migration_qt_calibration_edit.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-calibration-edit-new
./.venv/bin/python scripts/migration_qt_calibration_edit.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-calibration-edit-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_calibration_edit.py tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_workspace.py
```

保存4入力×9言語×両Qtで係数変更/原子的拒否/無効化/未指定channel追加、通常/Triggerの全resultとCSVを照合する。
BlackHoleは他のGUI/buildを止めて検査する。診断係数を物理校正の証拠にしない。
編集はセッション内だけで再開時は初期設定へ戻る。製品保存操作/互換/非同期化、物理校正/期限/map、長時間/性能/他OSは後続。

## 007-A 両Qt非同期保存操作の再検査

[手順](../native/qt-save.md)と[決定0026](decisions/0026-qt-snapshot-save.md)を参照。

```bash
./.venv/bin/python scripts/migration_qt_save.py --qt-prefix .tools/qt/6.11.2/macos --all-inputs --output .migration-local/007-save-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_save.py tests/logic_verification/test_migration_qt_display.py tests/logic_verification/test_migration_qt_workspace.py tests/logic_verification/test_migration_qt_trigger.py tests/logic_verification/test_migration_qt_calibration.py tests/logic_verification/test_migration_qt_calibration_edit.py
```

保存4/8ch f32/f64×9言語×両Qt。通常結果pin後の校正変更、全JSON/CSVの値/来歴、
I/O failureと復帰、Trigger保持/分離、queued-only取消/保存受付終了、取得停止/再開/Backend再生成/終了を検査する。
製品format接続は次節。BlackHole保存操作、長時間/負荷下/他OSは後続。

## 007-A 両Qt製品snapshot保存の再検査

[手順](../native/qt-save.md)と[決定0028](decisions/0028-qt-product-snapshot-save.md)を参照。

```bash
./.venv/bin/python scripts/migration_qt_save.py --qt-prefix .tools/qt/6.11.2/macos --product-format --all-inputs --output .migration-local/007-product-save-new
```

事前に両Qtと `result-candidate` をbuildする。保存4入力×9言語×両Qtから製品JSON/CSVを保存し、
Python互換reader/Rust reader/元bytes oracleで全snapshotを検査する。
既存sidecarの部分pair失敗、旧file保持/復元拒否、失敗後の復帰を追加する。
製品import UI/旧トレースnative import、再起動校正維持、取得中性能/他OSは後続。

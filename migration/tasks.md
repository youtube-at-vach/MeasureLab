# MIG-002後の実行単位

2026-10-01更新。Issue作成や技術採用の決定ではなく、このworktreeで再開するためのローカル作業票。
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
| 006-E | 不変result・channel校正・CSV/JSON来歴 | 003-B、006-B/C、P13/P14 | AC12、再読込、保存失敗、profile変更後の不変性、uncalibrated | 旧設定の自動移行 | 完了（2026-10-01、pure不変result/ID校正/JSON・CSV。保存2契約・4例と4/8ch f32/f64。製品互換/async/Qtは後続） |
| 007-A | 同じ結果をline/heatmapへ表示、操作/画像保存 | 004、006。P19のsnapshot境界 | AC05/07/08、軸/cursor/zoom・画像・再生成・サイズ/9言語 | 全41機能のUI | 進行中（2026-10-01、保存4/8ch f32/f64→実graph→両Qt表示の初期境界。実音声/trigger/9言語は後続） |
| 007-B | 描画/GUI遅延・CPU/RSS・表示編集時間 | 007-A、性能protocol | AC15/16。遅いGUIでも測定を保ち、単独/複数表示を比較 | 理論だけでの性能判定 | 未着手 |
| 008 | 2chフロー統合と四案の比較判断表 | 004〜007、実機/配布記録 | AC01〜16、仮想4/8ch回帰、採用/変更/段階導入/現行継続の理由と未確認点 | P3以降の自動開始、旧版置換 | 未着手 |

MIG-003はA/B/Cすべての入力/期待値と再現コマンドが揃うまで完了にしない。
MIG-004はSDK導入だけで完了にしない。OSや実機の不足はその試験だけを未確認として残し、
依存しないfixture/純粋演算/GUI境界の検証は進められる。
各試験の具体的な実行コマンドは実装と同時に作業票へ追加し、まだ存在しないrunnerを実行済みと記録しない。

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
NumPy-only CIは明示`--portable`。製品importer/非同期保存/cancel/Qt/実取得/校正mapは後続。

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
保存replayと英語QMLの初期境界まで。実音声表示/trigger UI/分離window/9言語・性能/他OSは後続。

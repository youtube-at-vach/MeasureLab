# MIG-002後の実行単位

2026-09-29。Issue作成や技術採用の決定ではなく、このworktreeで再開するためのローカル作業票。
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
| 004-A | Qt SDKを分離導入・版固定し、CXX-Qt/Qt Bridgeで同じ小画面 | 002-C/D。native内の薄いQt境界。導入前に現在の公式要件を確認 | Start/Stop、worker通知、list model、再生成/破棄、遅い通知、AC07/13。両方式の実行物と差分表 | 本格採用、41画面 | 未着手・SDK未導入 |
| 004-B | 上記のbuild/QML編集/packageと対象OS起動比較 | 004-A。同一workload/依存組合せとbenchmark記録 | AC16と性能protocol。Intel/ARM/Windows/Linuxの実行済み・未実行を分離 | 未所有環境の成功扱い、安定版配布 | 未着手 |
| 005-A | N-channel buffer/route/tap、backend共通境界 | 003-A/B。P02/P03。PortAudio基準とCPAL比較 | AC01〜03/09/11。4/8ch・非対称I/O・明示mapping・queue overflow。Rust追加時は独立CI追加 | network多ch拡張、全機器 | 未着手 |
| 005-B | 実機2ch、XRUN/再接続、排他/停止/時刻 | 005-Aと利用可能な実機。device/配線/校正を記録 | AC11/13/16、同じ配線で現行と交互測定。測定前に許容振幅差/遅延誤差を決める | 実機4/8/16ch保証 | 未着手・実機条件待ち |
| 006-A | FFT/窓/単位/PSDを参照比較 | 003-A、P04/P05。GUI非依存core | AC01/04、f32/f64・非2冪/極大・endpoint。必須数値条件合格、core編集時間記録 | 全解析モジュール | 未着手 |
| 006-B | 固定DAG・共有key・購読token・bounded cache | 006-A、003-B、P15 | AC05〜07。評価count/同一ID、条件分岐、独立平均、最後の解除/終了回収 | 汎用graph editor | 未着手 |
| 006-C | trigger/history・Timebase・generation・validity | 003-B、006-B、P03 | AC08/09、異なるcursor/通知遅延・保持超過・旧世代拒否。共有graphへ統合 | 外部trigger実機adapter | 未着手 |
| 006-D | 最小rate変換/filterとvalidity伝播 | 003-C、006-C、P06 | AC10/14、同じgraph内で遅延/区間/phase stateを保持 | 高品質resamplerの全機能 | 未着手 |
| 006-E | 不変result・channel校正・CSV/JSON来歴 | 003-B、006-B/C、P13/P14 | AC12、再読込、保存失敗、profile変更後の不変性、uncalibrated | 旧設定の自動移行 | 未着手 |
| 007-A | 同じ結果をline/heatmapへ表示、操作/画像保存 | 004、006。P19のsnapshot境界 | AC05/07/08、軸/cursor/zoom・画像・再生成・サイズ/9言語 | 全41機能のUI | 未着手 |
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
次は004-AのQt開発SDKの分離導入・版固定と、CXX-Qt/Qt Bridgeの比較。
005-A、006-Aも参照側の依存が揃った。候補実装の開始時はRust CI追加と同じfixtureの比較を行う。
MIG-006-Dでは一括APIをchunkごとに再起動せず、state/phase/validityをgraph内で保持する。

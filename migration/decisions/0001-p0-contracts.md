# 0001: P0契約と現行参照の境界

日付: 2026-09-29。状態: 検証用v0.1。対象: MIG-002。Rust/QML採用は未決定。

## 決定

41モジュールと共通機能は[機能台帳](../inventory.md)、共有能力は[プリミティブ台帳](../primitives.md)で追跡する。
Channel/Stream/時刻/validityを実装言語に先立って定め、最初のfixtureと候補実装は
[コア契約](../contracts/core.md)と[数値契約](../contracts/numerics.md)のv0.1を使う。
機能の移行状態は全件未着手のまま開始する。

参照は開始時mainの`9fd79958f6a8bbae6808813d3704617612e6d26c`に固定。
P0の許容差・反復速度予算は評価開始の基準であり、達成実績や将来の全機能への一律条件ではない。
比較が成立しなければ、期待値と実装を一緒に書換える前に原因と契約変更を記録する。

## 現行コードから分かった差

| 根拠 | 現行の意味 | 次期で検証すること |
| --- | --- | --- |
| [RingBuffer.write/read_with_metadata](../../src/core/ring_buffer.py) | 任意ch、絶対位置/gap、単一read位置。mono broadcast/切捨て/padding | 明示的mapping、購読者別cursorと同一区間snapshot |
| [AudioEngine._master_callback等](../../src/core/audio_engine.py) | 論理I/Oは1/2ch、前回のmix/DUT出力を量子化/mute前でloopback | N/M独立、tapの来歴、明示遅延、物理出力との区別 |
| [FFTManager.rfft](../../src/core/fft_manager.py) | planとbufferの共有、結果copy | 同じ条件のFFT結果を一度計算して共有、条件差で分岐 |
| [SpectrumAnalyzer._compute_standard](../../src/gui/widgets/spectrum_analyzer.py) | 全binへ2倍、物理単位では√2変換 | DC/Nyquistの理論値と旧表示を別保存。新FFT正規化へ無条件継承しない |
| [AudioCalc.resample](../../src/core/analysis.py) | Kaiser polyphase、rate≤0は入力を返す | 時刻/遅延/validityを付加し、無効rateは拒否。3-tap FIRは別の契約oracle |
| [CalibrationManager](../../src/core/calibration.py) | 感度/profile/周波数map、校正済み状態 | ChannelId別binding・revision・過去snapshot不変 |
| [ExportTrace](../../src/core/export/trace.py) | 軸/校正/metadata、mutable配列 | result不変、Stream/Timebase/区間/reasonの必須化、旧形式はunknownを保つadapter |

これらは今回の調査結果であり、現行製品の修正はこのタスクへ混ぜない。
DC/Nyquist等の数値差はMIG-003で再現して記録し、必要な現行版修正は別タスクにする。
code読解だけで実測済みの不具合と断定しない。

## 現在の適用範囲

MIG-003のfixture/runnerは作成済み。SDK/Qt・音声・FFT/graphの評価結果は[進捗](../status.md)を参照。
2026-10-04以降は[MIG-008の範囲](../../guide/RUST_QML_MIGRATION_PLAN.md)を優先する。
Windows・ARM、全機能/全tap/校正mapは延期。長時間試験と全条件の再検証は行わない。
契約変更が必要な場合は、影響するAC/fixtureと変更理由を既存の契約または進捗へ記録する。

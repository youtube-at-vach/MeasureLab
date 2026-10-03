# 0035: f32実入力からf64 filterへの明示精度境界

日付: 2026-10-03。MIG-006-D-explicit-f32-input。
状態: 取得owner内の一段変換候補。Rust/QML採用は未決定。
[正本計画](../../guide/RUST_QML_MIGRATION_PLAN.md)、[保存f64取得](0032-acquisition-filter-scheduler.md)、
[native callback](0034-native-portaudio-callback.md)、[再実行手順](../../native/filter-input.md)を参照。

## 判断

両backendの実入力はf32、保存取得で検証したfilterはf64。
暗黙変換やdevice f64対応という解釈を避け、解析ownerのfilter入口へ明示的な精度変換を追加する。
既存`Filter::new`はf32を拒否し、別の`new_with_conversion`への
`F32ToF64Exact`指定だけが元f32値の正確な拡張を許可する。
queue/元block/raw履歴をf64へ置き換えない。callbackの仕事と依存/lockfileは維持する。

親Sourceは実f32、出力Sourceはf64。metadataのconversionと出力のfilter revisionで
変換を識別し、同名のf64入力filterと共有FFT keyが衝突しないようにする。
変換なしの旧f64 identity/metadataは維持する。校正tapや物理clock写像は推測しない。
P2候補は既存係数の因果3-tap 48→24 kHzに固定し、Qt接続は次の境界とする。

## 検証と制約

保存FIRの5信号×2/4/8ch×正逆port順×5 patternを実queueで比較する。
新しいf32入力artifactに対する独立有限和とFFTを使い、元fixture/係数/許容差を変更しない。
旧f64の全21ケースも回帰する。正確な拡張、非有限/flags/gap、raw保持、共有/回収/世代を検査する。
期待値はcandidate requestへ渡さず、source/runner/binaryの前後一致と固定実体を保持する。

同じ取得ownerにCPAL/PortAudio native callbackを接続し、BlackHole各2/4/8chを短く比較する。
元f32の全bytes、filter全配列、共有FFT、選択tone、close/terminateを照合する。
結果/失敗/未実施とreportは[進捗](../status.md)に記録する。

f64 arithmeticのfilterへ拡張したのであり、f32 arithmeticのfilterやdevice f64の合格ではない。
Qtの派生通常/Trigger/result保存、動的route ack/全tap、製品設定UI/profile、性能/長時間/他OS、
MIG-008全体は残る。処理遅延と絶対clock写像はunknownを維持する。

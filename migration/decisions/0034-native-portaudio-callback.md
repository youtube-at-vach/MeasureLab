# 0034: PortAudio native callbackと両Qtのbackend選択

日付: 2026-10-03。MIG-005-A-native-callback-Qt。
状態: 評価用input.raw接続、共通backend全体は進行中。
[正本計画](../../guide/RUST_QML_MIGRATION_PLAN.md)、[共通入力境界](0033-common-backend-input.md)、
[再実行手順](../../native/callback-input.md)を参照。

## 判断

blocking PortAudio worker/pipeの成功だけでは、CPAL callback直結との取得境界やQtの寿命を比較できない。
次の単位として、native PortAudio callbackを既存の`InputWriter<f32>`へ直接接続し、
両Qtの共通display workerからrequestでbackendを選べるようにする。
旧requestはCPALを維持し、PortAudioには信頼するlibraryの絶対パスを明示する。

PortAudio C ABI/unsafeとlibrary寿命を専用`portaudio-input`へ隔離する。
新しい依存は固定したlibloading 0.8.9のみ。製品AudioEngineのcallbackは変更しない。
取得threadがlibrary/stream/contextを所有し、callbackは元f32をbounded queueへ書くだけとする。
1 processに1 native PortAudio入力ownerとし、close/terminateを確認できないときはcontext/libraryを保持してfailureにする。
XRUNの未知のsample位置を正常な連続入力へ置き換えず、明示abort/failureにする。

実backendの精度はf32のまま。一段f64 filterの精度境界やinput.calibratedを今回に混ぜない。
動的route/全tap、製品設定UI/永続profileは別の実装単位に残す。

## 検証範囲

callback元bits、無効block/XRUN、clock/port/library拒否、開始/停止/close/terminate失敗の寿命をdevice不要で検査する。
同じ実行物でBlackHoleの論理2/4/8ch×両QtをPortAudioとCPALそれぞれで検査する。
元f32/独立FFT/選択tone、共有表示、世代/購読/停止回収、library/source/binary hashを記録する。
既存保存fixture/数値許容差は維持する。件数・成功・失敗・reportは[進捗](../status.md)に残す。

短い診断は同条件性能/10分×3回、USB/絶対遅延、他OS/配布やMIG-008-A全フローの合格ではない。
Rust/QML採用、公開ABI、全機器対応、安定版置換は決定しない。

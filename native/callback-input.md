# Native PortAudio callback input

MIG-005-A-native-callback-Qt、2026-10-03。評価用PortAudio callbackを、CPALと同じ
`InputWriter<f32>`、取得owner、履歴、共有FFT、両Qtのline/heatmapへ接続する。
[決定0034](../migration/decisions/0034-native-portaudio-callback.md)と[進捗](../migration/status.md)を参照。

## 接続と所有権

`portaudio-input`だけにPortAudio v19 C ABIとunsafe境界を置く。
`audio-probe`、`audio-core`、graph、displayは従来のsafe Rust境界を保つ。
`libloading 0.8.9`を固定し、信頼する既存のPortAudio libraryを絶対パスで明示する。
libraryのインストール・既定deviceへのfallback・Python callback・pipeは含まない。

取得requestの`live.backend`は`Cpal`または`PortAudio`。
省略した旧requestは`Cpal`。`PortAudio`だけ`live.library`を要求する。
device/物理channel数/port/ID/rate/精度/世代/clockを開始前に照合し、
`portaudio.device:<name>`と`cpal.device:<name>`のclockを同一と推測しない。
これはrequestによるbackend選択で、製品GUIの設定画面・再起動profileではない。

`Pa_GetVersion`でv19 ABIを確認し、`Pa_IsFormatSupported`と`Pa_GetStreamInfo`で48 kHzを照合し、
`Pa_OpenStream`は明示deviceのinterleaved f32・256 frameを要求する。
macOSでは既存診断と同じCore Audioのchange-parameters/fail-if-conversion flagsを使う。
指定BlackHoleのrate/frame sizeは変わりうるが、既定device設定は変更しない。
callbackは固定容量8192 frameのqueueへ元f32を書き、atomic counterを更新する。
FFT、allocation、lock、JSON/ファイル操作、精度変換はcallbackへ入れない。
backend時刻は未検証なので原点・clock mappingはunknownを保つ。

ローカルのPortAudio V19.7.0-develは`PaStreamInfo.structVersion=0`を返す。
公式v19.7の[stream初期化](https://raw.githubusercontent.com/PortAudio/portaudio/v19.7.0/src/common/pa_stream.c)も
このfieldを設定していないため、ABI検査は`Pa_GetVersion`を使う。
structVersionは診断値として保持し、実sample rateの検査は維持する。

status flag、null/0/8192超frame、queue書込み拒否はcallbackをabortする。
backend XRUNの欠落位置を連続sampleとして捏造しない。
queue overwriteの正確な半開gapは既存queue/取得ownerで扱い、今回の短い実診断ではfailureにする。

開く・開始する・閉じる・terminateする操作は取得threadに置く。
1 processに1 native PortAudio入力ownerを許可し、競合ownerは待たずに拒否する。
複数viewは同じ取得ownerを共有する。これは製品の汎用PortAudio runtimeではない。
callback contextをBoxで固定し、library/context/排他leaseをclose/terminate成功まで保持する。
abort失敗でもcloseを試し、close/terminateの失敗はstop errorにする。
最終Dropでも解放を確認できない場合はlibrary/context/leaseを保持し、危険なpointer解放を避ける。
その場合は資源回収試験の不合格であり、正常停止の合格には数えない。

## 検証と再実行

[native環境](README.md#このworktreeで使う)と[Qt SDK](qt-probe.md#導入とビルド)を設定し、
リポジトリルートから実行する。既存PortAudio libraryの明示パスは環境ごとに確認する。

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p portaudio-input -p audio-probe -p display-core --features live-audio
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_live.py
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --backend PortAudio --portaudio-library "$PWD/.venv/lib/python3.12/site-packages/_sounddevice_data/portaudio-binaries/libportaudio.dylib" --qt-prefix .tools/qt/6.11.2/macos --output .migration-local/portaudio-callback-qt-new
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --backend Cpal --qt-prefix .tools/qt/6.11.2/macos --output .migration-local/cpal-callback-qt-new
```

runnerは明示BlackHole 2ch/16chの論理2/4/8chと非対称portを使い、
各方式の3取得世代、開始/停止/取消/失敗、遅いGUI、共有line/heatmap、分離と購読解除を検査する。
完成窓の元f32 bytesを独立NumPy FFTと選択toneへ照合し、
精度/ID/Timebase/全bin/未校正unknown、停止後のstream close・PortAudio terminate・graph回収を要求する。
PortAudio成功をblocking worker transportの成功やCPAL結果で代用しない。
library/binary/全native sourceのhashと実行コマンドをreportへ保存し、比較前後の一致を要求する。

保存32条件の共通入力比較は[既存手順](backend-input.md)のまま再検査する。
Native CIにはdevice不要のcallback/拒否/資源寿命テストを追加した。
remote CIとLinux実PortAudio入力は別の未確認項目とする。

動的出力route ack/全tap、現行Python AudioEngineのcallback、製品backend設定UI、
f32→f64/filter/派生Trigger保存、長時間/性能/他OS/clean配布、MIG-008-A統合は残る。

## ABI参照

実装した型・callback規則・寿命は公式の
[PortAudio v19 API](https://portaudio.com/docs/v19-doxydocs/portaudio_8h.html)、
[C header](https://portaudio.com/docs/v19-doxydocs/portaudio_8h_source.html)、
[Core Audio header](https://portaudio.com/docs/v19-doxydocs/pa__mac__core_8h_source.html)、
[libloading API](https://docs.rs/libloading/0.8.9/libloading/struct.Library.html)を参照する。
OS/ABI/機器の汎用保証や公開APIの採用判断は固定しない。

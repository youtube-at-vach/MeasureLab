# Common backend input boundary

MIG-005-A-common-input、2026-10-03。CPALとPortAudioの`input.raw`を同じ型付きqueue、
取得owner、worker所有履歴、共有FFTへ通す評価。製品backend共通化全体は進行中。
[決定0033](../migration/decisions/0033-common-backend-input.md)と[進捗](../migration/status.md)を参照。

## 接続と精度

`audio-core::backend::InputBinding`はbackend名、明示device名、物理入力数、実sample精度と
`IoFormat`のID/port/rate/世代/clockを検証する。clockは`cpal.device:<name>`または
`portaudio.device:<name>`で、両backendのclockを同一と推測しない。
原点・不確かさはunknownのまま。出力bindingやtapをinputとして代用しない。

`InputWriter<T>`とconsumerは単一ownerでCloneできない。設定は作成後に不変。
`write_next`は元のProducerと同じ固定容量・allocation/lock-freeの書込みで、CPALの実callbackから使用する。
worker transportの`write_at`は世代/位置も照合し、拒否時はqueue/位置を変更しない。
queue overwriteは既存の正確な半開gapを保持する。backend欠落で位置が不明な場合は明示failure。
f32/f64の暗黙変換、portの複製/切捨て、旧世代queueの再利用は行わない。

CPALの既存両Qt表示は同じ`InputWriter<f32>`へ接続した。保存f32/f64のworker入力にも同じ境界を使用する。
実PortAudioは評価用Python adapter workerのblocking `InputStream.read(256)`から
binary pipe経由で同じRust queueへ配送し、取得中に履歴/FFTを進める。
pipe/JSON/ファイル操作をaudio callbackへ入れない。製品AudioEngineのcallbackやQtのbackend選択は未接続。
PortAudio内部bufferとpipeもあるため、この試作の転送費用をcallback直結と同じと扱わない。

ローカルsounddeviceの`_check_dtype`は`float64`を`float32`へ変更する。実試験は明示f32だけで、
実streamのdtype/rate/channel数を確認する。保存f64の成功は実device f64対応の証拠ではない。
一段filter候補は引き続きf64因果3-tap 48→24 kHz。f32実入力からの接続は、
明示変換ノード/来歴または別の対応精度を決めてから行う。現在は未接続。

## 保存transportと証拠

`backend-input-candidate REQUEST.json WIRE.bin|- NEW_OUTPUT_DIRECTORY`を使う。
requestには期待値を渡さず、binding/FFT/queue/入力frame上限だけを指定する。
wireは各blockの32-byte little-endian headerと元精度のframe-major bytes。
headerはframes:u32、flags:u32、start:u64、generation:u64、first_seconds:f64の順。
NaN secondsはunknown、Infinityは拒否。終端はflags=0/NaN secondsの明示0-frame header。
途中EOF、末尾bytes、位置/世代不一致、8192 frame超過を拒否する。

入力は最大262,144 frame/16ch、requestのqueueは最大8192 frame。
pollは1024配送/1窓、履歴は2 FFT窓。診断archiveは元frame上限に従って保持するが、
外部snapshot/JSON/allocatorを含むprocess RSSの上限とは別。
streaming入力はその場で解析し、全出力のencode/I/Oはproducer終了・graph回収後に行う。
JSON/CSVには停止後も不変の最後の完成snapshotを保存する。

保存4/8ch f32/f64 × 両backend binding × 正順/逆順 × boxcar/Hannの32条件を検査する。
backend bindingの保存試験は実deviceを開かない。元fixture全体をverifyし、期待値/許容差を更新しない。
元bytes/選択portを厳密比較し、各共有complex FFTは独立NumPyへ照合する。
相対列/軸/単位/精度、未校正のunknown、JSON/CSV完全往復、停止後のpinと資源回収も照合する。
世代/shape/time/破損/切断transport、queue overwrite、nonfinite/flagsの無効窓は別テストで検査する。

## 再実行

リポジトリルートから[native環境](README.md#このworktreeで使う)を設定する。

```bash
./.venv/bin/python scripts/migration_backend_input.py --output .migration-local/backend-input-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_backend_input.py
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p audio-core -p graph-core -p audio-probe
```

別環境の保存比較は`--portable`を明示する。NumPyだけで実行でき、Qt/sounddeviceをimportしない。
BlackHoleの明示device試験は次のとおり。新しい出力先以外は拒否する。

```bash
./.venv/bin/python scripts/migration_backend_input.py --virtual-device --output .migration-local/backend-input-live-new
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 1 --output .migration-local/backend-input-cpal-qt-new
```

PortAudioは2ch/16chの明示入力から論理2/4/8chを選択し、各98,304 frameを解析する。
生成器も同じBlackHoleの指定portへ出力する。default device設定は変更しない。
Core Audioでは既存診断と同じexact-rate設定を使用するため、指定BlackHoleのrate/frame sizeは変わりうる。
実元bytes、独立FFT、選択tone、stream close、overflow/statusなしを確認する。
CPALは両Qtの既存寿命/分離/共有表示の回帰で検査する。
短い診断をAC15/16の性能、実clock/電圧/遅延、USB復帰の合格にしない。

reportにはsource/binary/fixture/入力/出力hash、条件/コマンド/全窓を保持する。
比較前後でsource/binaryが変われば合格にしない。失敗reportと途中入力も保持する。
[Native CI](../.github/workflows/native-evaluation.yml)へ保存比較と拒否テストを追加した。remote成功は未確認。

`input.calibrated`、output.mixed/post_dut/device_buffer、PortAudioの製品callback/Qt接続、
f64 filter/派生Trigger保存、失敗復帰/長時間/他OS/配布と008-A全フローは未完了。
未実装DUTはpost_dutとmixedを同じtapとして扱わない。

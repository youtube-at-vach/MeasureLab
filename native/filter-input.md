# Explicit f32 input / f64 filter boundary

MIG-006-D-explicit-f32-input、2026-10-03。P2候補の因果3-tap `[0.25, 0.5, 0.25]`、
48→24 kHzを既存の取得ownerへ接続する。Rust/QML採用と008-A全体は未完了。
[保存f64取得](filter-acquisition.md)、[native callback](callback-input.md)、
[決定0035](../migration/decisions/0035-explicit-filter-input.md)、[進捗](../migration/status.md)を参照。

## 精度と所有

`Filter::new`は従来どおりf64だけを受け付ける。f32は
`Filter::new_with_conversion(..., Some(InputConversion::F32ToF64Exact))`で明示する。
`Acquisition<f32>`のqueue/元block/履歴/raw FFTはf32のまま。
filterの解析workerが元の各f32を`f64::from`で拡張してから既存f64 stateを処理する。
audio callbackで変換・allocation・file I/Oを行わない。deviceの実精度がf64になったとは扱わない。

`FilterMetadata.parent`には元のf32 SourceとTimebaseを保持し、`output`はf64。
`input_conversion: F32ToF64Exact`と出力の`filter_state_revision`内の
`f32-to-f64-exact-v1`で変換の来歴とFFT keyの識別を残す。
変換のないf64 metadata/identityは維持し、未指定f32やf64への変換指定は拒否する。
raw port順・backend flags・非有限値のvalidity・欠落のsupport・世代fenceを維持する。
処理遅延と未検証clock写像はunknown。親Trigger1024→派生512、信号遅延1/2 output sampleを分ける。

一つのfilter stateと専用履歴/共有FFTを使う。最終購読解除・stop/restartの回収は既存取得ownerに従う。
Qtの通常/Trigger表示と保存は現在rawで、派生resultのQt接続は次の作業単位とする。

## 保存入力の再検査

[native環境](README.md#このworktreeで使う)を設定し、ルートで実行する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core -p audio-core
./.venv/bin/python scripts/migration_filter_input.py --output .migration-local/filter-input-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_input_candidate.py tests/logic_verification/test_migration_filter_candidate.py tests/logic_verification/test_migration_audio_graph.py tests/logic_verification/test_migration_trigger_candidate.py
```

保存済みFIRのimpulse-even/odd、DC、tone、gapを基に、新しいf32入力artifactを作る。
元fixture/係数/期待値/許容差は書き換えない。2/4/8chの各channelに異なる二進有理数scaleを与え、
正逆port順の30条件×5 callback patternを実queueへ通す。
元値の正確な拡張、独立有限和、独立NumPy FFT、全派生窓/invalidity、共有ID/平均reset、
poll上限と回収を要求する。gapは実overwriteで`[100,104)`を発生させる。
旧f64の21ケース×5 patternは別途回帰し、f32に丸めた入力へ旧f64期待値を流用しない。

report、request/入力/全出力、source snapshot、実行物、全artifact hashを新しい出力先へ保持する。
`evidence-audit.json`は同階層のfileを照合できる。source/runner/binaryの比較前後一致を要求する。
別環境の保存比較だけ`--portable`を明示する。Native CIにも保存比較を追加した。

## BlackHoleの短い診断

```bash
./.venv/bin/python scripts/migration_filter_live.py --virtual-device --portaudio-library "$PWD/.venv/lib/python3.12/site-packages/_sounddevice_data/portaudio-binaries/libportaudio.dylib" --output .migration-local/filter-live-new
```

macOSのBlackHole 2ch/16chに限定し、libraryは絶対パスで明示する。
同じ`filter-input-live`実行物でCPAL/PortAudioの各論理2/4/8chを順に検査する。
native callback→共通f32 queue→明示変換→一段f64 filter→派生履歴/共有FFTを通す。
各8192 raw frame、64派生窓、非対称portの固有tone/振幅を照合する。
元f32の全bytes、全filter配列、最初の有効complex FFT、窓ID/validityとstream closeを保存する。
file/JSONはstream停止後に書く。XRUN/gap/非有限/timeoutは診断failureにする。
PortAudioの実48 kHzとterminateも要求する。library/source/binaryを固定保存する。

この短い診断は負荷超過回復、長時間性能、絶対遅延、物理clock、他OS/配布の合格ではない。
f32演算filter、chain/SOS gap回復、全tap、製品設定UI/profile、Qt派生Trigger/保存、
008-Aの生成から保存までの全フロー統合は残る。

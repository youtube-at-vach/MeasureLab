# Filter / derived Trigger / Qt snapshot integration

MIG-006-D-filter-Qt、2026-10-03。既存の取得ownerへ固定P2候補の因果3-tap
`[0.25, 0.5, 0.25]`、48→24 kHzを接続し、両Qtのline/heatmap、派生Trigger、
校正付き不変snapshotのv1/製品JSON・CSV保存を同じ経路で検査する。
[精度境界](filter-input.md)、[決定0036](../migration/decisions/0036-filter-qt-integration.md)、
[進捗](../migration/status.md)を参照。Rust/QML採用と008-A全体は未完了。

## 選択と所有

requestの`filter`省略/`null`は従来のraw表示を維持する。
f32は`"filter": {"input_conversion": "F32ToF64Exact"}`を明示し、
保存f64は`"filter": {"input_conversion": null}`とする。
48 kHz以外、未指定f32変換、f64への変換指定、未知fieldはdevice open前に拒否する。
係数・rate・中心補償・chainの汎用編集UIは作らず、最初のP2候補に限定する。

`n`は表示/Triggerの派生窓長。保存replayの親入力は`2*n` frame。
元fixtureから切り出す2ch入力は新しい診断artifactに保存し、元fixtureは変更しない。
raw queue/履歴は元精度、filter/派生履歴/共有FFTはf64。変換とfilter処理は解析ownerに置く。
固定の正確な出力FFT keyを先に購読し、一つのfilter stateをattachする。
両viewのtokenは同じFFTを共有し、最終解除・stop/restartでgraph/filter/履歴を回収する。
callback、Qt、file workerからfilter stateを呼ばない。

raw履歴は`16*n`、派生履歴は`8*n` frameで独立に制限する。
各pollの配送は1024 frame、raw/派生窓はそれぞれ1窓以内。
replayはcallback chunkごとにqueueと残る窓をdrainする。
liveの正しさ診断はXRUN/gap/timeoutをfailureにし、長時間回復の合格には使わない。

## Triggerと保存

手動Triggerのevent、pre/post、fractional residualは明示的に派生Stream/Timebaseのdomain。
親eventを暗黙に写像せず、因果遅延をTrigger位置へ加減しない。
親1024→派生512の写像と、1/2 output sampleの信号遅延は既存filter metadataで別に保持する。
pending/gapの履歴は数値snapshotを作らず、明示retry・共有FFT cache・hold/releaseを維持する。
一方のviewの解除、遅いGUI、分離/再接続、stop/restart/Qt object再生成でも外部snapshotは不変。

`MeasurementResult.conditions.filter`へ親/出力Source、精度変換、rate比、信号遅延、
unknownの処理遅延とclockを保持する。raw snapshotにはfieldを追加しない。
codecの読込み時も出力identity、親世代/精度、rate/遅延の整合性を検査する。
校正は親のdevice/portへ照合したsession ID profileを派生結果へ後段適用する。
`input.calibrated` tapの実装とは扱わない。

両Qtは同じ完成resultをpinしてv1 JSON/CSVと製品carrier/CSV sidecarへ非同期保存する。
4形式の全配列・null/reason・校正・来歴を照合し、GUI外のwriter joinを維持する。
plot軸は結果のStream/周波数軸が変わったときに初期化し、同じ軸の更新では独立zoomを維持する。

## 再検査

[native環境](README.md#このworktreeで使う)を設定して両実行物とcodecをbuildする。

```bash
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display -p graph-core
./.venv/bin/python scripts/migration_qt_filter.py --qt-prefix .tools/qt/6.11.2/macos --output .migration-local/filter-qt-saved-new
./.venv/bin/python scripts/migration_qt_filter.py --qt-prefix .tools/qt/6.11.2/macos --forward --output .migration-local/filter-qt-forward-new
./.venv/bin/python scripts/migration_qt_filter.py --qt-prefix .tools/qt/6.11.2/macos --channels 2 --precision F32 --window SymmetricHann --language en --language ja --language de --language es --language fr --language ko --language pt --language ru --language zh --output .migration-local/filter-qt-languages-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_filter.py
```

既定の保存入力はf32/f64×2/4/8ch×Boxcar/Hann×両Qtの24条件、逆port。
`--forward`で正portを検査する。別OSの保存比較だけ`--portable`を明示する。
runnerは独立有限和とNumPy FFTで全相対列/校正を照合し、元filter/FFTの許容差を維持する。
最初の窓はwarmup `[0,1)`で、正常数値へ置き換えない。

BlackHoleの短い診断:

```bash
./.venv/bin/python scripts/migration_qt_filter.py --qt-prefix .tools/qt/6.11.2/macos --virtual-device --portaudio-library "$PWD/.venv/lib/python3.12/site-packages/_sounddevice_data/portaudio-binaries/libportaudio.dylib" --output .migration-local/filter-qt-live-new
```

CPAL/PortAudio×2/4/8ch×Boxcar/Hann×両Qtを順に実行する。
system defaultへfallbackしない。入力f32は解析ownerで最大32 MiB/世代まで保持し、
入力診断archiveとfirst/Trigger証拠のfile/JSON出力はstream停止後に行う。
上限超過はfailureで、切捨てない。製品/v1の非同期保存workerは取得中も動く。
これは任意の製品保存予算ではなく、独立有限和へ照合する診断用archive。
first/Triggerの親supportも保存し、全通常/Trigger保存を実取得値へ照合する。
全source/runner/binary/libraryを比較前後で照合し、固定実体と全artifact hashを保存する。

全tap/動的route ack、取得profileの再起動永続化、親Trigger adapter、f32演算/chain/SOS gap回復、
長時間性能、物理clock/絶対遅延、他OS/clean配布、008-Aの生成から保存までの全統合は残る。

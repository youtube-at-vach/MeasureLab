# BlackHole実入力の共有result表示

MIG-007-Aの実入力境界。保存入力の[表示検証](display-candidate.md)へCPALのinput.rawを接続する。
Rust/QML、Qt adapter、rendererの採用判断ではない。現在のPython製品engine/UIは変更しない。

## 再実行

[環境](README.md#このworktreeで使う)のRust/Qt SDKを設定する。
既存のBlackHole 2ch／16chを完全一致で指定し、既定deviceへのfallbackは行わない。
出力刺激はBlackHoleにのみ送る。system default deviceは変更しない。
48 kHz／256 frameの設定を明示するため、指定したBlackHoleのdevice設定を変更しうる。

```bash
export QMAKE="$PWD/.tools/qt/6.11.2/macos/bin/qmake"
cargo +1.98.1 build --offline --locked --manifest-path native/Cargo.toml -p cxxqt-display -p qtbridge-display
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p display-core --features live-audio
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p audio-probe
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --repeat 3 --output .migration-local/007-live-new
./.venv/bin/pytest -q tests/logic_verification/test_migration_qt_live.py tests/logic_verification/test_migration_qt_display.py
```

runnerはmacOSで明示`--virtual-device`を付けた場合だけdeviceを開く。
2chの逆順bindingと、16chから飛び飛びに4ch／8chを選ぶbindingを両Qt方式へ通す。
`--case 2-to-2`、`--case 4-from-16`、`--case 8-from-16`で条件を限定できる。
出力は1024 sample周期、各論理chに異なるbinと振幅`(ch+1)/512 FS peak`を持つf32 cosine。
未選択portには異なる小振幅toneを入れ、誤bindingや暗黙補完を検出する。

各実行で3世代の取得窓bytes、完全な不変result、停止後のcallback/queue/graph診断とPNGを保存する。
取得窓の全binを独立したNumPy f64 FFTへ照合し、既存[数値契約](../migration/contracts/numerics.md)の
f32許容差`atol=2e-6, rtol=2e-5`をそのまま使う。f32演算をf64演算と同一に扱わない。
portごとのbin／振幅は別に`1e-6 FS`で検査する。元fixture・契約・許容差は変更しない。
markerだけでは合格にしない。取得bytes、metadata、stream回収、PNGのCRC/寸法/両plot画素を要求する。
新しい出力directoryを指定し、保存済みrunを上書きしない。

## 所有権と停止

- [CPAL入力owner](audio-probe/src/live.rs)を解析threadで作成・開始・停止・破棄する。
  callbackは容量8192 frameのqueueとatomic counterのみを操作する。mutex・JSON・ファイルI/Oは使わない。
- [実入力scheduler](display-core/src/live.rs)が最大1024 frame／1窓を2 ms間隔でpollする。
  履歴は2N、入力はf32／48 kHz、FFTは最大4096 frame、論理chとdeviceは最大16ch。
  実graphの購読／raw allocation共有／不変result／容量1のGUI通知は保存replayと共通。
- 準備中cancel、二重開始／停止、最後の需要解除、再オープン、QObject再生成と動作中終了を検査する。
  GUIを320 ms止めても解析threadを動かし、古い通知を世代で拒否する。
- queue gap、callback失敗、3秒無入力を明示failureにする。短い正しさ検証の方針であり、
  製品のXRUN継続／USB復帰方針ではない。停止失敗も成功にしない。
- backend timestampからclock原点・不確かさを推定しない。両方null、電圧はnull＋uncalibratedのまま。
  stream破棄後の診断とgraphのnode/subscription/cache/in-flight回収を保存する。

## 手動表示と残る範囲

runnerが生成した`request.json`をコピーし、`evidence`を`null`にするか、新しい空directoryへ変更する。
[Qt実行環境](qt-probe.md#共通画面と自動検証)を設定して起動する。

```bash
export MEASURELAB_DISPLAY_REQUEST="$PWD/.migration-local/manual-live-request.json"
native/target/debug/cxxqt-display --live-input
native/target/debug/qtbridge-display --live-input
```

別途BlackHoleへ信号を流すとStart inputで表示する。入力源はrequestで決まり、
`--live-input`は評価画面の文言と自動試験のtone条件を選ぶ。
ch/cursor/zoom、Stop/Recreate/Save imageは保存表示と同じ操作。
[分離Windowと起動時の9言語](workspace-display.md)も同じ画面へ接続する。

AC01/05/07/13のBlackHole input.raw→両Qt表示まで。物理ADC/DAC・絶対遅延・USB復帰・長時間、
全tap／製品共通adapter、trigger／校正／製品保存UI、実window manager、10分性能、他OS／配布は残る。
9言語QMLの分離操作は保存入力で検査する。実入力は英語回帰で、実window manager/他OSの合格には数えない。
最終実施結果は[進捗](../migration/status.md)、判断境界は[決定0017](../migration/decisions/0017-live-result-display.md)を参照。

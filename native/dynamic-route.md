# Dynamic output route candidate

MIG-005-A、2026-10-01。既存の[音声境界](audio-boundary.md)へ制御→callbackの配送を追加した。
[決定0015](../migration/decisions/0015-dynamic-output-route.md)と[進捗](../migration/status.md)を参照。
製品backendの変更、全tap/Qt統合、Rust/QML採用の決定ではない。

## 配送と所有権

[route_mailbox](audio-core/src/dynamic_route.rs)は単一所有の制御handleとcallback handleを作る。
sourceの順序、outputのID/port順序、generationは開始時に固定する。並替え、複製、mix、符号、zeroはgain行列で変える。
物理port bindingの変更は新しいendpoint/generationを作る。旧endpointへ新旧の世代を混ぜない。

制御側で検証・compileした有限gainだけを、固定16×16 termsのatomic mailboxへ書く。
未確認の要求は1件まで。busy、無効route、旧世代、逆順の要求は現在のrouteを変更せず拒否する。
callbackはblockのshape/位置を検証してから、要求位置以上の最初のblock境界で係数をコピーする。
要求が遅れて届いた場合も実際の開始sampleをackへ残す。block途中で分割しない。

callback内の変更は固定回数のatomic load/storeと固定配列へのcopy。lock、待機loop、alloc、解放、文字列処理はない。
EMPTY→PENDING→APPLIEDのAcquire/Releaseでpayloadの所有権を移し、ackを読んだ制御側だけが次を書ける。
active係数はmailboxから独立し、遅いack readerでも音声を続ける。unsafeを使わない。
source列を参照するtermの加算順とzero係数の除外は既存CompiledRouteと同じ。
f32入力をf64でmixし、最後にf32へ戻す。clipping/正規化を追加しない。

callbackのBlockRouteはgeneration、数値sequence、半開区間だけを返す。
文字列revision、要求/実適用sample、applied/cancelledは制御側のRouteEventへ保存する。
公開済みblockのsequenceやbytesは後の変更で書き換えない。
closeは冪等。進行中のblockは完了しうるため、未適用要求のcancelはcallback破棄後に確定する。
handle、stream、Arcの破棄は制御側で行う。通常のcallback演算が破棄を行うAPIではない。

## 保存入力による検査

ローカルRust環境は[準備手順](README.md#このworktreeで使う)を参照。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p audio-core -p audio-probe
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p audio-core -p audio-probe --all-targets -- -D warnings
./.venv/bin/python scripts/migration_audio_route.py --report .migration-local/005-route-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_audio_route.py
```

[offline driver](audio-core/src/bin/route-candidate.rs)へ003-Bの元の4/8ch f32 bytesを通す。
4→2/8、8→4/16出力、256 frame固定/非整列の可変block、1/4 blockおきのack確認の12件。
要求257/1025/2049に対し2件目はsend_after=1536として意図的に遅く送る。
独立Pythonのsample位置モデルと手計算の境界を使い、candidateのackを期待値として使わない。
期待値・参照fixtureをRustへ送らず、保存fixtureも更新しない。

選択/並替え/複製/mix/zero、全blockのgeneration/sequence/区間、要求/実位置/revision、
output.mixedとmute後device_bufferのbytesを照合する。
空のFS合計は既存CompiledRouteのIEEE符号付きzeroを保つ。muteは+0を提出する。
f64取得fixtureは既存queueの回帰で検査するが、このcallback候補はf32だけ。
reportへsource/binary/lock/fixture hash、実行argv/終了コード/時間、gzip log/hashを保存する。
`--portable`はNumPyだけの環境で使え、Qt/SciPy/FFTW/音声依存なしでも同じ12件を検査する。

## BlackHoleの短時間診断

```bash
./.venv/bin/python scripts/migration_audio_route.py --virtual-device --output .migration-local/005-route-blackhole-new
```

既存ディレクトリは拒否する。明示flagなしではdeviceを開かない。
通常の回帰はBlackHole 2ch／16chを完全一致で指定し、system defaultへfallbackしない。
CPAL 0.18.2、48 kHz、256 frame、f32、4秒、2→2/4→16/8→16を各3回とPreparing cancelを使う。
全routeのshape/ID/世代/時刻順序をdevice open前に検証し、未完了scheduleはreport保存後に失敗を返す。

route_updatesはroute、generation、requested_sample、send_after_sampleを持つ。
初期revisionはsequence=0、更新はsequence=1から。制御loopが配送し、CPAL出力callbackが適用する。
ack位置は`output-callback.frame`のdomain。入力sampleやbackend secondsへ暗黙に変換しない。
manifestのdynamic_routesと出力raw bytesの絶対sampleから適用区間を検査する。
取得graphは従来どおりinput.rawの物理bindingを保持し、出力revisionを入力へ事後適用しない。

診断は実ackから提出値を別の行列演算で再構成し、全sample誤差2e-6 FS、markerのchannel差1 frameを要求する。
実ack自体も要求/配送位置以上、256 frame境界、世代/sequence/revision/完了件数で検査する。
input.raw→履歴→共有FFTの評価件数/共有/回収、error/XRUN/gap/muteも既存validatorで検査する。
CPALでcopyするtapはdevice提出buffer。output.mixedの実取得queueやgraph購読はまだ作らない。

内部mailbox/係数は固定容量。外部snapshot、制御metadata、reportの成長、全process RSSの上限ではない。
短時間のCPAL診断で、PortAudioとの動的比較、3×10分、CPU/RSS/GUI遅延予算には数えない。
全tap、PortAudio製品共通adapter、Qt、実取得校正/非同期保存、device/host時刻写像、USB復帰、排他、他OSは後続。

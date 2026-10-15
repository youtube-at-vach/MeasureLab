# Rust の検証

合否・試験条件・許容差はテストコードとQAのassertionを正本とする。過去のテスト件数・ビルド成功を現行版の保証にしない。共通チェックは [Tool Usage Guide](../../.agents/workflows/tool_usage.md)、次の受け入れ条件は [PLAN](PLAN.md)。以下は必要な確認を選ぶための入口で、全作業で実機QAを実行する指示ではない。

## テストコードの入口

各モジュールの`#[cfg(test)]`／`tests`と独立参照式を読む。条件を変えるときは根拠と許容差もコードへ反映し、文書へ同じ数値表を複製しない。

| 対象 | 正本 |
| --- | --- |
| PCM入力・可変callback・CH・Fs・有限終端 | [audio.rs](../../src/audio.rs)、[measurement.rs](../../src/measurement.rs) |
| 履歴・トリガー・Scope統計・Single／Autoset・XY | [signal.rs](../../src/signal.rs)、[acquisition.rs](../../src/acquisition.rs)、[xy.rs](../../src/xy.rs)、[cursor.rs](../../src/cursor.rs) |
| Spectrumの全サイズ・窓・精度・独立FFT／Parseval・校正 | [spectrum.rs](../../src/spectrum.rs)、[calibration.rs](../../src/calibration.rs) |
| 全窓／最新窓、欠落、UI受信停止・世代・有限Stop、STFT | [spectrum_worker.rs](../../src/spectrum_worker.rs)、[stft.rs](../../src/stft.rs)、[measurement.rs](../../src/measurement.rs) |
| REF・局所位相・二段EMA・校正・無効化・専用転送 | [lockin.rs](../../src/lockin.rs)、[lockin_worker.rs](../../src/lockin_worker.rs)、[loopback.rs](../../src/loopback.rs) |
| Generatorの独立式・遷移・長い整数時計・優先Stop | [generator/tests.rs](../../src/generator/tests.rs)、[generator/control.rs](../../src/generator/control.rs) |
| 出力PCM・デバイス・通知・解放・外部履歴 | [output/device.rs](../../src/output/device.rs)、[output/runtime.rs](../../src/output/runtime.rs)、[output/history.rs](../../src/output/history.rs)、[callback_profile.rs](../../src/callback_profile.rs) |
| 同期比較の独立DFT・既知遅延・雑音・有限平均・無効化 | [comparison.rs](../../src/comparison.rs)、[comparison/tests.rs](../../src/comparison/tests.rs)、[comparison_worker.rs](../../src/comparison_worker.rs) |
| 設定／結果の互換性・f64往復・不正参照・条件差抑止・原子的保存 | [settings.rs](../../src/settings.rs)、[export.rs](../../src/export.rs)、[results.rs](../../src/results.rs)、[file_io.rs](../../src/file_io.rs) |
| GUI・内部／外部の統合、画像の読み戻し | [app.rs](../../src/app.rs) のQA分岐、[generator_panel.rs](../../src/app/generator_panel.rs)、[comparison_panel.rs](../../src/app/comparison_panel.rs)、[gpu.rs](../../src/gpu.rs)、[qa.rs](../../src/qa.rs) |
| 実入力の独立適合／DFT、固定周期のQA出力 | [qa/physical_lockin.rs](../../src/qa/physical_lockin.rs)、[qa/comparison.rs](../../src/qa/comparison.rs)、[qa/output.rs](../../src/qa/output.rs) |
| 反復CPU性能 | [benches/](../../benches)、[共通harness](../../benches/common/mod.rs) |

たとえばGUIなしの測定ワーカー回帰は次で実行できる。対象名は`measurement::tests`を`generator::tests`や`comparison::tests`等へ置き換える。これは共通のGUIなし／通常／全機能チェックの代用ではない。

```sh
./scripts/cargo.sh test --locked --lib --no-default-features measurement::tests
```

## GUI・入出力QAの再実行

リポジトリのルートでQA版を一度ビルドし、同じ実行ファイルを直列で使う。異なる機能構成のビルドは同じ実行ファイルを上書きするため並行実行しない。実時間試験中はビルド・別の音声試験を並行させず、画面スリープ抑止・並行作業の有無を条件に残す。

```sh
./scripts/cargo.sh build --release --locked --features qa
target/release/measurelab --help
target/release/measurelab --gpu-smoke
target/release/measurelab --ui-smoke
```

GUI smokeは7計器の選択・再選択、追加・除去、単独／コンソール往復、構成置換の取消が取得世代・解析設定・保持値・出力コマンドを変えないことも検証する。複数区画では実際の描画が割当寸法に収まることを確認する。クリック・ホバー、入力欄編集中・修飾キー付き・長押しのSpaceは`app/shell.rs`のeguiイベントテスト、旧設定移行・版5往復は`settings.rs`を正本とする。

GUI再設計の内部受け入れをまとめて再実行する。実際のshellウィジェットへのクリック・キーイベント、7計器の未取得画面、通常幅・狭幅、コンソールの配置、共通入出力・詳細欄、通常Generatorの内部経路、同期比較、保持結果の保存・別プロセス復元・再測定を直列に実行し、ケースごとの画像・ログとソース／バイナリ識別を`dist/gui-redesign-qa/`へ残す。

```sh
./.venv/bin/python scripts/qa_gui_redesign.py
./.venv/bin/python scripts/qa_gui_redesign.py --device "BlackHole 2ch" --device "BlackHole 16ch"
./.venv/bin/python scripts/qa_gui_redesign.py --device "ZOOM UAC-232"
```

`--binary target/debug/measurelab`でQAの開発ビルドを使える。`--case scope-compact`等で一部だけ再実行できるが、`held-replay`は先に`held-save`を完了する。外部の`held-…-replay`も対応する`held-…-save`を先に実行する。`--device`を明示すると通常Generatorの実出力と外部保持結果の保存・別プロセス復元・再測定を追加する。`--device "ZOOM UAC-232"`にはL出力→L入力／R出力→R入力のTRS接続が必要で、最大0.1 FS peak・DCなしを出力する。

外部保持QAの固定信号出力も通常の入出力と同じ`audio::measurement_stream_config()`を使う。CoreAudioのバッファ設定は同一デバイスの入出力で共有されるため、一方だけ既定バッファへ戻さない。設定はログの`QA output configuration`で確認し、起動エラーや通知監査の失敗を除外して合格にしない。

`widget-interactions`は [gui_qa.rs](../../src/app/gui_qa.rs) で実際の共通枠・メニュー・詳細欄をeguiイベントから操作する。構成置換の取消、7計器の追加・除去、キーボード選択、入出力画面からの復帰、狭幅・倍率・模擬native scaleへの往復で、入力世代・測定条件・保持結果・出力コマンドが変わらないことを検証する。前面のメニューや編集ウィンドウから背後の区画を選択しないことは`app/shell.rs`のイベントテストで確認する。

成功判定はassertionと撮影成功で、画像の読み取りやすさは別に確認する。イベント試験・模擬scaleは、通常ビルドの手動操作と実モニター間のネイティブDPI切り替えの受け入れを代用しない。

撮影できないデスクトップでは`--assertions-only --output dist/gui-redesign-assertions`で状態遷移・数値・描画寸法だけを実行できる。このモードは画像を要求せず、manifestの`screenshots_required: false`と各ログに未撮影を残す。撮影込みの失敗をこのモードの成功で置き換えず、画像・通常GUIの受け入れは未完了のまま扱う。

macOSのMetalは、画面が点いていても他のウィンドウに覆われた計器を`Occluded`としてフレーム取得を省略する。eguiのviewport情報が`occluded: None`でも、この判定は起こる。撮影要求の後に取得が省略されると、GPU読み戻しが始まらず撮影を受信できない。`--ui-smoke`は短時間のQAウィンドウを前面に保持し、取得失敗の最初の4件と総数を記録する。フォーカス状態だけで撮影可否を判定しない。

`caffeinate -du ./.venv/bin/python scripts/qa_gui_redesign.py`は実行中だけ画面スリープを抑止する。遮蔽の診断は停止画面の`MEASURELAB_UI_SMOKE_IDLE=1`と`MEASURELAB_UI_SMOKE_FOREGROUND=0`（通常の重なり順）／`bottom`（背面固定）で再現できる。既定は前面保持。撮影失敗を`--assertions-only`で成功へ置き換えない。

`--gpu-smoke`は通常ビルドでも使える。`--ui-smoke`は画像を`dist/ui-smoke.png`へ保存する。数値照合と実際の撮影成功は別に確認する。通常起動は入力停止状態、`--demo`はQA専用。Software Loopbackと通常Generatorはqaなしでも使える。

### G4に残る手動受け入れ

通常ビルドを`target/release/measurelab`で起動し、以下を確認する。音声デバイスを使わない操作確認は、I/OのSoftware LoopbackまたはGeneratorの内部接続で行える。

1. 7計器の選択・再選択、コンソールへの追加・除去・単独表示との往復、詳細・入出力画面からの復帰を行い、選択対象と構成が保たれることを確認する。
2. Generatorを内部接続で出力し、入力停止後やGenerator非表示中にも共通バーの出力状態を読め、Stop outputで停止できることを確認する。数値入力中のSpaceで入力が開始・停止しないことも確認する。
3. 通常幅・最小幅付近・表示倍率変更で、対象名・主要値・有効性・停止操作を確認する。狭幅から戻したときにコンソールの希望配置・比率が戻ることを確認する。
4. 異なるネイティブDPIの実モニター間でウィンドウを往復させ、同じ表示・操作を確認する。モニターの用意がない場合は未確認のまま残し、表示倍率や模擬scaleで代用しない。

実施後は下記の要約に対象ビルド・モニター条件・結果を短く反映する。自動QAの成功だけでこの手動受け入れを完了にしない。

### GUI QAの環境変数

主要なGUI選択（詳細な選択肢は`src/app.rs`の同名環境変数を参照）:

| 環境変数 | 確認すること |
| --- | --- |
| `MEASURELAB_UI_SMOKE_SETTINGS`／`VIEW`／`ADJUST` | 共通入出力画面・単独／コンソール表示・選択中の詳細。`VIEW=scope`／`spectrum`／`spectrogram`／`xy`／`lockin`／`comparison`／`generator`で単独、`all`は4区画、`console`は7計器、`empty`は空コンソール。`DETAILS=1`は狭幅の詳細編集。変数名の共通接頭辞は`MEASURELAB_UI_SMOKE_` |
| `MEASURELAB_UI_SMOKE_INTERACTIONS=1` | 実際のshellウィジェットを使ったクリック・キー・狭幅・倍率・模擬native scaleの状態遷移。音声ランタイムを重複生成しない |
| `MEASURELAB_UI_SMOKE_LAYOUT=columns`／`rows`／`grid`／`tabs` | コンソールの希望配置。タブ列の折り返し後の残り寸法で退避を判断し、描画と同じ区画寸法で検証 |
| `MEASURELAB_UI_SMOKE_SCOPE4=1` | 内部4ch波形、CH別レンジ・オフセットと下部バー。物理4ch入力の確認ではない |
| `MEASURELAB_UI_SMOKE_ROUTING=1`／`CALIBRATION=1`／`CURSORS=1` | 16ch割当・内部校正・カーソル。物理校正の確認ではない |
| `MEASURELAB_UI_SMOKE_STAGE3F=1`＋`REPLAY=1`／`COMPARE=1` | Software Loopbackの保存・別プロセス復元・再測定・参照比較 |
| `MEASURELAB_UI_SMOKE_LOCKIN=polar` | R／θ。`cartesian`／`all`／`pair`／`settling`／`ref-loss`／`held-edit`／`live-edit`／`source-change`で他の状態 |
| `MEASURELAB_UI_SMOKE_GENERATOR=scope` | 内部GeneratorとScope。`spectrum`／`lockin`／`only`／`narrow`／`workspace`で他の配置 |
| `MEASURELAB_UI_SMOKE_GENERATOR_DEVICE="BlackHole 16ch"` | 通常GeneratorのCPAL出力と実入力。物理接続では`ZOOM UAC-232`を明示指定 |
| `MEASURELAB_UI_SMOKE_COMPARISON=pair` | Software Loopbackによる比較のライブCH交換・保持・保存復元。`narrow`でサイドバー、その他の値で比較単独表示 |
| `MEASURELAB_UI_SMOKE_IDLE=1` | 未取得の停止画面。実入力・出力は開始せず撮影 |
| `MEASURELAB_UI_SMOKE_COMPARISON_AXIS=log`／`full`／`custom` | 比較の対数／Nyquist全域／700〜800 Hz表示。解析条件は保持 |
| `MEASURELAB_UI_SMOKE_GENERATOR_COLLAPSED=1` | Generator信号編集部を閉じた状態でのグラフ配分 |
| `MEASURELAB_UI_SMOKE_ZOOM=1.25`／`--compact` | 表示倍率／狭幅。DPI切り替えの実機確認は別途必要 |

表で省略した環境変数名も共通接頭辞を付ける。再起動QAでは先に保存用実行を完了する。例:

```sh
MEASURELAB_UI_SMOKE_STAGE3F=1 target/release/measurelab --ui-smoke
MEASURELAB_UI_SMOKE_STAGE3F=1 MEASURELAB_UI_SMOKE_REPLAY=1 \
    MEASURELAB_UI_SMOKE_COMPARE=1 target/release/measurelab --ui-smoke --compact
MEASURELAB_UI_SMOKE_GENERATOR=narrow target/release/measurelab --ui-smoke
MEASURELAB_UI_SMOKE_COMPARISON=pair target/release/measurelab --ui-smoke
```

通常Generatorの内部／外部GUI QAには同じ入力窓の比較DFT照合も含む。外部では`MEASURELAB_UI_SMOKE_GENERATOR=scope`と`MEASURELAB_UI_SMOKE_GENERATOR_DEVICE`を組み合わせる。連続出力profileには`MEASURELAB_PROFILE_COMPARISON=1`を追加できる。

外部I/Oは`--list-devices`で名前・対応Fsを確認する。`--audio-smoke`は2秒の取得、`--stft-smoke`は連続STFT、`--channel`は1始まり。BlackHole専用の既知出力QAと通常Generatorの出力を区別する。

```sh
target/release/measurelab --list-devices
target/release/measurelab --audio-smoke --input-device "BlackHole 16ch"
target/release/measurelab --stft-smoke --input-device "BlackHole 16ch" --channel 16 --sample-rate 96000
target/release/measurelab --multichannel-smoke
target/release/measurelab --lockin-smoke --input-device "BlackHole 2ch" --sample-rate 48000
```

物理QAはUAC-232のL出力→L入力、R出力→R入力を用意し、明示指定で最大0.1 FS peak・DCなしを出力する。独立した生入力適合との一致を判定し、DAC電圧・ADCゲイン・実Fsの校正精度へ読み替えない。

```sh
MEASURELAB_LOCKIN_SECONDS=10 target/release/measurelab --physical-lockin-smoke \
    --input-device "ZOOM UAC-232" --sample-rate 48000
./.venv/bin/python scripts/validate_stage4_macos.py --suite ui
./.venv/bin/python scripts/validate_stage4_macos.py --suite physical --physical --seconds 30
```

[macOS統合runner](../../scripts/validate_stage4_macos.py) はケース・ソース／バイナリSHA-256・終了結果を保存し、失敗で停止する。`--case`で対象を絞る。`--suite load --seconds 600`は負荷評価。QAの起動待ち中通知と測定区間の失敗は別記録で、通常版の失敗判定を緩めない。通常Generatorは開始時通知も失敗として監査する。

## 性能・継続性

[profile-stage2.sh](../../scripts/profile-stage2.sh) はログ・RSS・CPUを`dist/stage2-qa/`へ保存する。主要な選択は [qa.rs](../../src/qa.rs) と`src/app.rs`を参照する。窓サイズ・精度・更新モード・表示数・入力・スリープ抑止を揃えて比較する。

```sh
MEASURELAB_PROFILE_SECONDS=120 ./scripts/profile-stage2.sh demo-120 --demo
MEASURELAB_PROFILE_SECONDS=30 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_SPECTRUM_MODE=continuous MEASURELAB_PROFILE_KNOWN_OUTPUT=1 \
    ./scripts/profile-stage2.sh large-fft-30
MEASURELAB_PROFILE_SECONDS=300 MEASURELAB_PROFILE_DEVICE="ZOOM UAC-232" \
    MEASURELAB_PROFILE_SAMPLE_RATE=48000 MEASURELAB_PROFILE_FFT_SIZE=8192 \
    MEASURELAB_PROFILE_SPECTRUM_MODE=continuous MEASURELAB_PROFILE_UI_STALL=1 \
    MEASURELAB_PROFILE_GENERATOR_DEVICE="ZOOM UAC-232" \
    MEASURELAB_PROFILE_GENERATOR_EDITS=1 ./scripts/profile-stage2.sh generator-uac232-300
```

GeneratorのUI停止はRUNNING・遷移外・1秒分以上のPCM進行後に行い、入力・出力・解析の継続をそれぞれ判定する。有限Stop、独立数値照合、ストリーム／通知リスナー解放後の通知監査までを必要とし、途中終了・ログの欠落0だけで合格にしない。実USB切断の選択は`MEASURELAB_PROFILE_GENERATOR_DISCONNECT=1`で、準備完了後の手動切断・再接続を伴う。

Spectrum遅延は同じ結果群の入力利用可能→解析完了→UI提出をCPU時刻で直接集計する。p95の合計・差は使わず、ADC取得時刻・GPU完了・scanout・窓充填／平均整定とは区別する。コールバック計測はプリエンプション込みのホスト経過時間で、厳密なスレッドCPU時間ではない。QA計測の追加メモリ・転送負荷も条件へ含める。

反復性能は`cargo bench --locked --no-default-features`で測る。`cargo test`によるbench各条件1回は動作確認で、性能判定には使わない。

## コードで代替できない確認の要約

以下は2026-10-12〜15の条件付き観測。共通環境はmacOS 14.8.9・x86_64・Rust 1.99、GUIはMetal／AMD Radeon R9 M290X。Fsは公称、入出力FS・物理時計・CH間校正は未校正。基点SHAの上の作業差分が対象であり、SHAだけを検証済みソースとしない。

| 対象・基点／条件 | 確認した範囲と制限 |
| --- | --- |
| GUI G4、`32ec3f5d`＋G4差分／dev QA・native pixels per point 2.0・画面スリープ抑止 | 7計器、単独／コンソール・4区画・狭幅・倍率・詳細・入出力画面の画像を確認。内部経路とBlackHole 2ch／16ch・48 kHz・f32の通常Generator、独立Lock-in／比較照合、UI停止中の継続、有限Stop、保持・JSON／CSV・OFF復元・別プロセス再測定を確認。背面固定ではMetalの`Occluded`と撮影タイムアウト、前面保持では撮影成功を再現した。ソース／バイナリ識別・ログ・画像は`dist/gui-redesign-g4-acceptance/manifest.json`、遮蔽の比較は`dist/gui-capture-diagnosis/occlusion/`。通常ビルドの手動操作・実モニター間DPI切り替えは未確認 |
| GUI G4のUAC-232、同差分／48 kHz・2ch・f32・L/L、R/R TRS・1,024 frames | 右経路の復旧後、通常Generatorの同じ生入力窓の独立Lock-in／同期比較照合、UI停止中の継続、有限Stop、保持・設定／結果・CSV／PNG保存、OFF復元・参照比較・別プロセス再測定を確認。固定信号のQA出力はバッファ要求を通常入力と統一し、起動／測定／解放後の通知監査も通過。証拠は同manifestの`generator-zoom-uac-232`と`held-zoom-uac-232-*`。未校正の物理振幅・時計、最大Fs、反復再接続、長時間は未受け入れ |
| Lock-in、`a837b04c`／BlackHole 2ch・16ch、44.1／48／96／192 kHz | 短時間の数値・欠落回復・保存再測定。2ch・48 kHzはGUIなし600秒、正常測定区間の通知・欠落0。物理精度・通常GUI600秒の保証ではない |
| Lock-in、`1c0373dc`／UAC-232 LL／RR TRS、同4レート | 同じ生入力窓の独立適合・保存再取得。48 kHzはGUIなし600秒、最大R差0.598 µFS peak・位相差0.0004101°。−40 dB応答で高レベル基準から約0.115〜0.155°の位相変化があり原因未確定 |
| 段階4、`60021e3f`／Software Loopback・BlackHole・UAC-232 | 通常幅・狭幅、別プロセス復元・再測定、画像保存。BlackHole 16ch・96 kHz・512k Continuousは30秒、20予定窓・入力／解析欠落0。UAC-232・48 kHzの30秒はUI停止中の継続・有限Stop・独立照合・解放後監査を確認 |
| 同段階4、UAC-232・48 kHz・4表示・512k | 約270秒・95窓・捕捉欠落0までの観測を受け入れ。中断時に入力通知2件、最終有限照合・監査なし。600秒完走の成功ではない |
| 内部Generator、`6c6feaad`／2ch・48 kHz・f64 | 750 Hz・0.125／0.0625 FS peak・+30°、Scope／Spectrum／Lock-in、1秒UI受信停止・独立Stop・JSON／CSV・OFF復元を確認 |
| 通常Generator実出力、`03622c6f`／BlackHole 2ch・16ch・UAC-232、48 kHz・f32 | 750 Hz・0.1／0.05 FS peak・+30°、Scope／Spectrum／Lock-in、独立Stop、JSON／CSV・OFF復元を条件付き確認。通常幅1440×860・狭幅900×660の旧GUI確認で、後の表示変更・DPI切り替えの確認ではない |
| Generator負荷、`2b723c2e`／UAC-232・48 kHz・f32・1,024 frames | 300秒指定（取得約299.82秒・出力約299.33秒）・100編集、入出力通知と取得／解析欠落0、1秒UI停止・最終独立照合・有限Stop・解放後監査。編集応答p95 33.601 ms、出力callback経過時間p95上端0.07 ms・実ブロック時間の0.4% |
| 実USB切断、`83a0421b`／UAC-232・48 kHz・2ch・f32・dev QA | ERROR保持・入力停止・出力解放、再接続と同じ出力条件の復元でOFFを確認。再接続後のStart・測定・反復切断は未確認 |
| 同期比較、`83a0421b`／Software Loopback・48 kHz・750 Hz、N=4,096・平均4 | ゲイン0.5・+30°、CH交換で2.0・−30°、有限Stop・保存・OFF復元・再測定を確認。後の表示修正、通常Generator内部／BlackHole／UAC-232の独立DFT統合は未確認 |

CoreAudioの起動／再接続XrunはBlackHole・UAC-232で発生した。バッファ要求変更後の上記UAC-232成功は全起動・他Fsの保証ではなく、初期試験の操作介入の可能性と原因は未確定。接続直後のSingle・外部可変callback・物理16ch・他OS／機器・実時計／物理校正・GPU実行／実表示遅延は確認を残す。

詳細な旧記録は [整理前のGit履歴](https://github.com/youtube-at-vach/MeasureLab/tree/61b36dc3/guide/rust/validation) で必要時だけ参照する。ローカル証拠は`dist/stage4-macos-qa/`、`dist/generator-qa/`、`dist/lockin-physical-qa/`等のmanifest・JSON・ログ・画像で、Git管理外のため新しいcheckoutに存在するとは限らない。新しい実機確認は対象リビジョン／差分・バイナリ識別、環境・条件、判定・失敗・未確認範囲を短く更新し、試行ごとの経過を文書へ追加しない。

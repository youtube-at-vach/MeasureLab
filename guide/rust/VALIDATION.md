# Rust の検証

合否・試験条件・許容差はテストコードとQAのassertionを正本とする。過去のテスト件数・ビルド成功を現行版の保証にしない。共通チェックは [Tool Usage Guide](../../.agents/workflows/tool_usage.md)、次の受け入れ条件は [PLAN](PLAN.md)。以下は必要な確認を選ぶための入口で、全作業で実機QAを実行する指示ではない。

## 検証対象環境と既存成果物

現在のIntel MacではGUI操作手段の技術的制約により、通常ビルドの手動GUI操作チェックと実モニター間DPI操作を検証計画から除外する。この環境の手動操作を公開前の未完了条件に数えず、対象外として記録する。以下の手動確認手順は操作可能な他環境を対象とする。実行可能な自動イベント・撮影・数値照合・連続動作評価は継続し、対象外を合格として扱わない。測定精度・実入出力・配布物の同一性などの条件は維持する。

既存の成功ログと実行ファイルは、対象ソース・機能構成・プロファイル・バイナリのハッシュが一致することを確認して再利用する。同じ条件のビルド・テストを重複実行せず、未実施条件と変更の影響範囲を追加検証する。文書だけの更新でRustの実装・依存・ビルド条件が変わらない場合は、その範囲を明記する。QA版の結果をqaなし配布物の受け入れへ、別SHAの結果を公開候補へ読み替えない。

## 物理デバイスの安全制約

測定・出力中のUSB抜去試験は機器を破損する可能性があるため、今後実施しない。これは物理デバイスの安全上の必須制約であり、検証項目・P1の未確認範囲・公開判断の例外として残さない。接続を変更するときは、入力と出力の両方を停止し、ストリームの解放を確認してから行う。

エラー処理は模擬通知・callback停止のコード検証で確認する。実機での再接続は上記の停止・解放後に行い、復元後OFF→明示Start→再測定を別に確認する。模擬エラーの成功を物理抜去の確認済みとは説明しない。旧`MEASURELAB_PROFILE_GENERATOR_DISCONNECT`は廃止し、設定されていれば通常版・QA版とも入出力やGUIの起動前に拒否する。

## テストコードの入口

各モジュールの`#[cfg(test)]`／`tests`と独立参照式を読む。条件を変えるときは根拠と許容差もコードへ反映し、文書へ同じ数値表を複製しない。

| 対象 | 正本 |
| --- | --- |
| PCM入力・可変callback・CH・Fs・有限終端 | [audio.rs](../../src/audio.rs)、[measurement.rs](../../src/measurement.rs) |
| 履歴・トリガー・Scope統計・Single／Autoset・XY | [signal.rs](../../src/signal.rs)、[acquisition.rs](../../src/acquisition.rs)、[xy.rs](../../src/xy.rs)、[cursor.rs](../../src/cursor.rs) |
| Spectrumの全サイズ・窓・精度・独立FFT／Parseval・校正、ESDのパルス窓長不変性・白色雑音 | [spectrum.rs](../../src/spectrum.rs)、[ESD数値テスト](../../src/spectrum/esd_tests.rs)、[calibration.rs](../../src/calibration.rs) |
| 全窓／最新窓、欠落、UI受信停止・世代・有限Stop、STFT | [spectrum_worker.rs](../../src/spectrum_worker.rs)、[stft.rs](../../src/stft.rs)、[measurement.rs](../../src/measurement.rs) |
| 起動時の取得バックログ・STFT消費の遅延 | [stft.rs](../../src/stft.rs)の`capture_backlog_survives_delayed_stft_start_without_losing_windows`。192／768 kHz・CH 16で取得キュー全量と端数ブロックを先行投入し、整数窓・f64振幅・欠落なしを確認 |
| QA撮影の遅い保存・有界転送・保存失敗 | [qa/screenshot.rs](../../src/qa/screenshot.rs)。PNG・ファイルI/OはGUI外で最大1件、完了を受信するまで次の画像を受け付けない |
| STFTの3 Overlap・全FFT長／精度・長いサンプル時刻・履歴Spectrumの微小値／無効値 | [stft.rs](../../src/stft.rs)のOverlap／retained_spectrumテスト。数値読出しは[spectrum.rs](../../src/spectrum.rs)の`Result::from_stft`を共有 |
| STFT表示要求・縮約・固定上端・不規則FPSのスクロール・Liveの描画先端と下端の被覆・キャッシュ容量 | [spectrogram/viewport.rs](../../src/spectrogram/viewport.rs)、[spectrogram/scroll.rs](../../src/spectrogram/scroll.rs)。GPU読み戻しは`--gpu-smoke`のラスタDC／Nyquist、時間移動・未取得区間の空白と転送省略 |
| STFT数値履歴・UI受信停止・周回・不変参照・容量と世代 | [spectrogram/history.rs](../../src/spectrogram/history.rs)。実時間の収集継続は`MEASURELAB_PROFILE_UI_STALL` |
| STFTのCPU容量・旧新世代の交換・終了時解放 | [spectrogram_capacity.rs](../../tests/spectrogram_capacity.rs)。独立プロセスの計数アロケーターでFFT・結果プール・履歴・Hold・選択Spectrum A／B・表示準備を合算。確保要求のpayloadとRSS・アロケーター管理費用を区別する |
| REF・局所位相・二段EMA・校正・無効化・専用転送 | [lockin.rs](../../src/lockin.rs)、[lockin_worker.rs](../../src/lockin_worker.rs)、[loopback.rs](../../src/loopback.rs) |
| Generatorの独立式・遷移・長い整数時計・優先Stop | [generator/tests.rs](../../src/generator/tests.rs)、[generator/control.rs](../../src/generator/control.rs) |
| 出力PCM・デバイス・通知・解放・外部履歴 | [output/device.rs](../../src/output/device.rs)、[output/dither.rs](../../src/output/dither.rs)、[output/runtime.rs](../../src/output/runtime.rs)、[output/history.rs](../../src/output/history.rs)、[callback_profile.rs](../../src/callback_profile.rs) |
| 同期比較の独立DFT・既知遅延・雑音・有限平均・無効化 | [comparison.rs](../../src/comparison.rs)、[comparison/tests.rs](../../src/comparison/tests.rs)、[comparison_worker.rs](../../src/comparison_worker.rs) |
| 設定／結果の互換性・f64往復・不正参照・条件差抑止・原子的保存 | [settings.rs](../../src/settings.rs)、[export.rs](../../src/export.rs)、[results.rs](../../src/results.rs)、[file_io.rs](../../src/file_io.rs) |
| 起動設定の保存・終了時flush・破損保護・機器不在／列挙順変更 | [settings/preferences.rs](../../src/settings/preferences.rs)、[app/preferences.rs](../../src/app/preferences.rs) の`startup-preferences` GUI QA |
| GUI・内部／外部の統合、画像の読み戻し | [app.rs](../../src/app.rs) のQA分岐、[generator_panel.rs](../../src/app/generator_panel.rs)、[comparison_panel.rs](../../src/app/comparison_panel.rs)、[gpu.rs](../../src/gpu.rs)、[qa.rs](../../src/qa.rs) |
| 実入力の独立適合／DFT、固定周期のQA出力 | [qa/physical_lockin.rs](../../src/qa/physical_lockin.rs)、[qa/comparison.rs](../../src/qa/comparison.rs)、[qa/output.rs](../../src/qa/output.rs) |
| 反復CPU性能 | [benches/](../../benches)、[共通harness](../../benches/common/mod.rs) |

たとえばGUIなしの測定ワーカー回帰は次で実行できる。対象名は`measurement::tests`を`generator::tests`や`comparison::tests`等へ置き換える。これは共通のGUIなし／通常／全機能チェックの代用ではない。

```sh
./scripts/cargo.sh test --locked --lib --no-default-features measurement::tests
```

## コア解析の負荷耐性QA

[analysis_resilience.rs](../../tests/analysis_resilience.rs)は、通常版と共通の入力転送・取得・Spectrum・STFT履歴収集・Lock-in・同期比較をGUIなしで同時実行する。既知f64信号、2／16ch、表示受信停止、有限Stop、同じワーカーの再開後の数値と世代分離を確認する。短い回帰は通常の`cargo test`に含まれる。

実時間試験はrelease・qaなしで明示的に実行する。CPU競合スレッドを継続実行し、取得・各解析の欠落、窓数、STFTキューの最大滞留、取得の進捗、Stop時間を`ANALYSIS_RESILIENCE`のJSONへ出力する。`processing_seconds`は計測区間の経過時間の合計で、スレッドCPU時間ではない。`core_max_lag_frames`は生成数と取得処理数の最大差で、受付欠落を含み、キュー滞留だけを表さない。欠落時のSpectrum・Lock-in・同期比較の更新窓数はリセット後の値とする。

```sh
MEASURELAB_STRESS_SECONDS=120 MEASURELAB_STRESS_RATE=192000 \
    MEASURELAB_STRESS_CHANNELS=16 MEASURELAB_STRESS_COMPETITORS=3 \
    MEASURELAB_STRESS_REQUIRE_CONTINUOUS=true \
    ./scripts/cargo.sh test --release --locked --no-default-features \
    --test analysis_resilience -- --ignored --nocapture
```

無欠落を受け入れる条件では`MEASURELAB_STRESS_REQUIRE_CONTINUOUS=true`を指定する。限界探索では省略し、欠落を含む結果を記録する。その場合も解析エラー・進捗停止・有限終端の不一致・再開後の数値不一致は失敗とする。入力レート・CH数・競合数・時間を変更し、同一条件の改善前後を複数回比較する。試験中はビルド・他の音声試験を並行実行せず、OS／CPU・Rust版・ソース差分・実行ファイル識別とログを`dist/`へ保存する。

実入力と同じワーカーへの模擬フレーム供給であり、OSの音声callback・物理入出力・GPU／表示応答の受け入れは別に行う。STFTは短時間の取得滞留に備える固定容量と、小さいFFTの高い行頻度に対応する小容量行の追加プールを持つ。大きいFFTは従来のフルサイズ行だけを使い、持続的な処理能力超過では欠落を明示する。CPU側の既定メモリ上限は容量テストで確認する。容量・負荷条件・許容差の正本はコードとする。

## GUI・入出力QAの再実行

リポジトリのルートでQA版を一度ビルドし、同じ実行ファイルを直列で使う。異なる機能構成のビルドは同じ実行ファイルを上書きするため並行実行しない。実時間試験中はビルド・別の音声試験を並行させず、画面スリープ抑止・並行作業の有無を条件に残す。

```sh
./scripts/cargo.sh build --release --locked --features qa
target/release/measurelab --help
target/release/measurelab --gpu-smoke
target/release/measurelab --ui-smoke
```

GUI smokeは7計器の選択・再選択、追加・除去、単独／コンソール往復、構成置換の取消が取得世代・解析設定・保持値・出力コマンドを変えないことも検証する。複数区画では実際の描画が割当寸法に収まることを確認する。クリック・ホバー、入力欄編集中・修飾キー付き・長押しのSpaceは`app/shell.rs`のeguiイベントテスト、旧設定移行・版6往復は`settings.rs`を正本とする。

GUI再設計の内部受け入れをまとめて再実行する。実際のshellウィジェットへのクリック・キーイベント、7計器の未取得画面、通常幅・狭幅、コンソールの配置、共通入出力・詳細欄、通常Generatorの内部経路、同期比較、保持結果の保存・別プロセス復元・再測定を直列に実行し、ケースごとの画像・ログとソース／バイナリ識別を`dist/gui-redesign-qa/`へ残す。

```sh
./.venv/bin/python scripts/qa_gui_redesign.py
./.venv/bin/python scripts/qa_gui_redesign.py --device "BlackHole 2ch" --device "BlackHole 16ch"
./.venv/bin/python scripts/qa_gui_redesign.py --device "ZOOM UAC-232"
```

`./scripts/cargo.sh build --profile dev-fast --locked --features qa`でQAの開発ビルドを用意し、`--binary target/dev-fast/measurelab`で画面・操作を確認できる。実時間・性能の受け入れはreleaseを使う。`--case scope-compact`等で一部だけ再実行できるが、`held-replay`は先に`held-save`を完了する。外部の`held-…-replay`も対応する`held-…-save`を先に実行する。`--device`を明示すると通常Generatorの実出力と外部保持結果の保存・別プロセス復元・再測定を追加する。`--device "ZOOM UAC-232"`にはL出力→L入力／R出力→R入力の接続が必要で、最大0.1 FS peak・DCなしを出力する。両CH TRSとL-L TRS／R-R XLR（−20 dB）のような異なる経路を区別して成果物に記録する。照合は同じ生入力窓に対して行い、減衰器の公称値から物理校正済みのゲインを仮定しない。

外部保持QAの固定信号出力も通常の入出力と同じ`audio::measurement_stream_config()`を使う。CoreAudioのバッファ設定は同一デバイスの入出力で共有されるため、一方だけ既定バッファへ戻さない。設定はログの`QA output configuration`で確認し、起動エラーや通知監査の失敗を除外して合格にしない。

`startup-preferences`は一時ファイルと模擬デバイスを使い、再起動相当の保存復元、非同期列挙待ち、順番・同名機器の変化、不在入力・出力の条件保持、停止中の再取得、破損ファイルの保護を確認します。入出力ストリームを開始せず、通常のユーザー設定を読み書きしません。`--case startup-preferences --binary target/dev-fast/measurelab`で対象だけ再実行できます。ファイル名・Unicodeパス・最新変更の終了時flushはRustテストで確認します。各OSの配布物での実機再起動受け入れとは区別します。

`widget-interactions`は [gui_qa.rs](../../src/app/gui_qa.rs) で実際の共通枠・メニュー・詳細欄をeguiイベントから操作する。構成置換の取消、7計器の追加・除去、キーボード選択、前面メニュー／Help／File paths & status操作中の背後選択の抑止、Escによる前面ウィンドウから入出力画面への段階的な復帰、狭幅・倍率・模擬native scaleへの往復で、入力世代・測定条件・保持結果・出力コマンドが変わらないことを検証する。操作名、カーソルの配置対象と配置済み状態、Clear cursorsの解除範囲も実ウィジェットで照合する。出力停止は模擬状態と停止コマンドだけを使い、完全停止時の無効化と、開始・設定適用待ち／停止処理中／エラー・復元中の停止要求を確認する。この試験では出力を開始しない。クリックの背後への伝播、数値編集のEscと詳細画面からの復帰の分離、ショートカットの修飾キー・長押し・一押し一回の条件は`app/shell.rs`のイベントテストで確認する。

停止中の`widget-interactions`は、Scope中央案内の未選択・CH数未確定・開始待ち・未取得・トリガー待ち・CH範囲外と、入力設定ボタンを検証する。模擬取得エラーの表示、停止後の波形・f64数値・欠落情報の保持、通常幅／狭幅での案内の配置・ボタン到達性、軸名の表示領域、用途説明が常時表示されないこと、単独／複数計器の見出しとトリガー設定／取得済みの区別も実ウィジェットで照合する。音声デバイスは開かず、撮影・手動操作の確認と分ける。

`widget-interactions`には [測定操作の回帰検証](../../src/app/gui_qa/measurement_ux.rs) も含みます。振幅比2:1の共通軸表示、CH選択での共通軸維持、独立設定の復帰、狭幅で波形を表示したまま時間軸を数値編集する操作、Generatorから入力設定への遷移と入出力コマンドの維持を確認します。Scope上部は取得・トリガー状態とカーソル、時間軸・CHレベル・Autosetの2行に収まること、停止したNormal／Singleでは保持波形の時間軸と編集値が区別されることを照合します。Scope下部のRMS／P-Pは共通単位とともに1行へ収め、通常幅・狭幅で桁数・指数表記・無効状態を変えても、ラベル・数値の右端・単位・CH枠・波形の座標が動かず、範囲外表示がCH枠内で重複しないことを描画命令で照合します。共通縦軸の旧設定互換・保存復元・不正値拒否は`settings.rs`を正本とします。

`scope-flow-*`は [Scope通しQA](../../src/app/gui_qa/scope.rs) で中央案内→入力設定→Software Loopback→取得→Stop・保持→Singleの待機・途中停止・完了→模擬エラー・再開を実ウィジェットと測定ワーカーで照合する。単独／複数計器、狭幅・倍率・模擬native scaleで条件・f64保持結果・出力コマンドを維持し、取得中の入力フレームとSpectrum解析の継続を確認する。`scope-generator-views`では通常Generatorの内部接続の取得中に同じ表示操作を行い、入力・Spectrum解析・出力サンプルの進行と出力世代・条件の維持を確認する。縦ガイド線はポインターの内外・退出と配置済みA／Bを区別して描画命令を検証し、`scope-pointer-inside`と`scope-flow-held-wide`の画像でも比較する。物理入出力は使わない。`widget-interactions`ではLock-inのStart analysis案内と同期比較の無効・入力停止・平均待ち・欠落・無効入力の説明も照合する。

共通I/Oの実ウィジェットでは共通Fs・個別Fs・Device defaultの切り替え、不正条件の拒否、再取得・復元待機中の操作抑止も確認する。合成した出力能力を使う16→2→1chの変更では、範囲外OUTの未割当・OFF、GEN ID・利用可能な割当・保持入力の維持を検証する。合成デバイスの試験では音声ストリームを開かず、実機の対応形式・測定精度の確認とは分ける。

サイドバーは [sidebar.rs](../../src/app/gui_qa/sidebar.rs) で通常／コンパクト切り替え、7計器の固定順序・再選択・名称ツールチップ、入出力画面からの復帰、コンソール、プロット幅の拡大、狭幅・模擬native scale往復と測定条件・保持結果・出力コマンドの維持を確認する。自動保存の既定値・不正値・往復は`app/shell.rs`のStorageテストを正本とする。`sidebar-expanded`／`sidebar-compact`／`sidebar-compact-held`／`sidebar-compact-running`で画面を撮影できる。

成功判定はassertionと撮影成功で、画像の読み取りやすさは別に確認する。イベント試験・模擬scaleは、通常ビルドの手動操作と実モニター間のネイティブDPI切り替えの受け入れを代用しない。

撮影できないデスクトップでは`--assertions-only --output dist/gui-redesign-assertions`で状態遷移・数値・描画寸法だけを実行できる。このモードは画像を要求せず、manifestの`screenshots_required: false`と各ログに未撮影を残す。撮影込みの失敗をこのモードの成功で置き換えず、対象環境で未実施の画像・手動操作と、Intel Macの手動操作の対象外を区別する。

macOSのMetalは、画面が点いていても他のウィンドウに覆われた計器を`Occluded`としてフレーム取得を省略する。eguiのviewport情報が`occluded: None`でも、この判定は起こる。撮影要求の後に取得が省略されると、GPU読み戻しが始まらず撮影を受信できない。`--ui-smoke`は短時間のQAウィンドウを前面に保持し、取得失敗の最初の4件と総数を記録する。フォーカス状態だけで撮影可否を判定しない。

`caffeinate -du ./.venv/bin/python scripts/qa_gui_redesign.py`は実行中だけ画面スリープを抑止する。遮蔽の診断は停止画面の`MEASURELAB_UI_SMOKE_IDLE=1`と`MEASURELAB_UI_SMOKE_FOREGROUND=0`（通常の重なり順）／`bottom`（背面固定）で再現できる。既定は前面保持。撮影失敗を`--assertions-only`で成功へ置き換えない。

`--gpu-smoke`は通常ビルドでも使える。`--ui-smoke`は画像を`dist/ui-smoke.png`へ保存する。数値照合と実際の撮影成功は別に確認する。通常起動は入力停止状態、`--demo`はQA専用。Software Loopbackと通常Generatorはqaなしでも使える。

### 多言語基盤（I5）

I5の独立した受け入れは完了し、以下を回帰検証の入口とする。APIの保存復元・未知locale・欠落／古い訳のフォールバック・固定／動的文言キャッシュ・編集IDとフォーカス、9localeの解決済みカタログ全文字の比例／等幅フォントを`src/i18n.rs`で検査する。翻訳タスクの準備・適用と、誤回答時にカタログを書かない条件は`scripts/test_i18n.py`で検査する。

```sh
./.venv/bin/python -m unittest discover -s scripts -p 'test_i18n.py'
./scripts/cargo.sh test --locked i18n::tests
./scripts/cargo.sh build --release --locked --features qa
caffeinate -du ./.venv/bin/python scripts/qa_gui_redesign.py \
    --case widget-interactions --case language-demo-controls \
    --case scope-generator-views --case scope-flow-held-wide \
    --output dist/i18n-i5
```

`gui_qa/language.rs`は実メニューへのクリックで全9localeを切り替え、通常幅・狭幅・zoom・模擬native scaleで入出力の開始／停止ラベル全体の表示と、選択・測定設定・校正・入力世代・出力コマンドの維持を確認する。`language-demo-controls`はデモ入力の長い開始ラベルも対象にする。保持中は入力条件・Scope生サンプル・欠落も比較する。通常Generatorの内部接続では入力フレームとSpectrum窓、出力の進行を確認し、既存の有限Stop・独立DFT／Lock-in照合・JSON／CSV再利用へ続ける。物理出力を使わない。

フレームCPUはフォント・レイアウトをウォームアップして、各localeと同じ画面の英語p95を比較する。メニュー切り替えに要した時間は別に記録し、GPU・scanout・物理入出力や、i18n導入前の性能を保証しない。試験中はビルド・別の音声試験を並行しない。許容差・合否はQAコードを正本とする。ログ・画像・ソース／バイナリ識別はGit管理外の指定出力先へ保存する。

通常desktop（qaなし）のAPIテスト・releaseビルドと`--gpu-smoke`も共通検証に含める。現在のIntel Macの手動操作・実モニター間DPIは既存方針により対象外。今後の翻訳は1言語・1グループの訳文・変数・用語・対象差分と共通検証を各PRで確認し、I5を翻訳ごとの手動受け入れ待ちへ戻さない。未翻訳は英語へ戻す。I5は基盤の受け入れであり、翻訳本文の網羅と訳語・レイアウトの視覚レビューはPLANのI4／I6で別に扱う。

### G4に残る手動受け入れ

操作可能な環境で通常ビルドを`target/release/measurelab`から起動し、以下を確認する。現在のIntel Macではこの節の手動操作チェックを実施せず、受け入れ待ちにも残さない。音声デバイスを使わない操作確認は、I/OのSoftware LoopbackまたはGeneratorの内部接続で行える。

1. 7計器の選択・再選択、コンソールへの追加・除去・単独表示との往復、詳細・入出力画面からの復帰を行い、選択対象と構成が保たれることを確認する。
2. Generatorを内部接続で出力し、入力停止後やGenerator非表示中にも共通バーの出力状態を読め、Stop outputで停止できることを確認する。数値入力中のSpaceで入力が開始・停止しないことも確認する。
3. 通常幅・最小幅付近・表示倍率変更で、対象名・主要値・有効性・停止操作を確認する。狭幅から戻したときにコンソールの希望配置・比率が戻ることを確認する。
4. 異なるネイティブDPIの実モニター間でウィンドウを往復させ、同じ表示・操作を確認する。モニターの用意がない場合は未確認のまま残し、表示倍率や模擬scaleで代用しない。

実施後は下記の要約に対象ビルド・モニター条件・結果を短く反映する。自動QAの成功だけでこの手動受け入れを完了にしない。

### Spectrogramの容量・比較負荷

S6のMVP基本受け入れは次のrunnerの`--basic`で直列に実行する。内部デモの3 Overlap、Software Loopback、通常Generatorの内部入力を扱い、`--device`は指定した仮想／物理経路を追加する。基本条件のUAC-232は48 kHz、Software Loopback・Generator・BlackHole 16chは192 kHzとする。UAC-232は両出力をそれぞれの入力へ接続し、DCなし・最大0.1 FS peakを出力する。実際のケーブル・減衰条件は`--physical-connection`へ記録する。測定中はビルド・別の音声試験を並行させない。

```sh
./scripts/cargo.sh build --release --locked --features qa
./.venv/bin/python scripts/qa_spectrogram.py --basic --output dist/spectrogram-s6-basic \
    --device "BlackHole 2ch" --device "BlackHole 16ch" --device "ZOOM UAC-232" \
    --physical-connection "L-L TRS; R-R XLR with -20 dB attenuator"
```

条件・許容差・操作応答の合否は[scripts/qa_spectrogram.py](../../scripts/qa_spectrogram.py)と[qa/spectrogram.rs](../../src/qa/spectrogram.rs)を正本とする。同じ入力条件のLive／stressを比較し、UI停止中の継続、世代不変、欠落、整数hopと窓数、保持した3時刻の生入力からの独立DFT、元のf64値によるSpectrum読出しを判定する。UI間隔のp95に加え、最大間隔・実行時間・フレーム数・操作数も判定し、長いGUI停止を少数の良好なp95で合格にしない。この回帰は`./.venv/bin/python -m unittest discover -s scripts -p 'test_qa_spectrogram.py'`で確認する。表示要求からUI適用までの遅延はキュー・表示準備・UI待ちを含み、GPU完了・scanout・ADC時刻は含まない。前面保持と画面スリープ抑止を使い、ウォームアップ後のsurface取得省略を合格にしない。起動直後の省略も総数には残す。

ログ・RSS・ソース／バイナリ識別と比較結果は指定した出力先の`manifest.json`へ保存する。基本と長時間の受け入れ範囲を`acceptance_scope`で区別し、`--basic`なしではUAC-232も192 kHzで長時間比較を行う。`--route software`等で一経路を選べる。任意の短縮試運転は受け入れ時間を満たした結果と区別し、失敗ログを成功で上書きしないよう`--output`を分ける。保存ログの再判定は`--audit path/to/manifest.json`で行い、元の判定を残した`manifest-audited.json`へ書き出す。

実ウィジェットのイベントと単独／Pair・通常幅／狭幅の画像は次で確認する。画像の可読性は別に読み取る。模擬倍率・イベントの成功を通常ビルドの手動操作や実モニター間DPIへ代用しない。

```sh
./.venv/bin/python scripts/qa_gui_redesign.py --output dist/spectrogram-s6-ui \
    --case spectrogram-display-single-wide --case spectrogram-display-single-compact \
    --case spectrogram-display-single-measurement-compact \
    --case spectrogram-display-pair-wide --case spectrogram-display-pair-compact
```

S3〜S5の有限入力テストは独立したテストプロセスで実行する。最大FFT・高Fs・16chからの選択と最小FFT・48 kHz・1chを切り替え、時間上限／容量上限、Hold中の周回、未受信の表示応答、要求飽和、旧新世代の交換、Live復帰と全ワーカー終了後の解放を確認する。精度・容量の判定はテストコードを正本とする。有限入力のペーシングは実時間の性能保証ではない。

```sh
./scripts/cargo.sh test --locked --no-default-features --test spectrogram_capacity -- --nocapture
./scripts/cargo.sh bench --locked --no-default-features --bench spectrogram
```

ベンチは実際のSTFT→数値履歴→表示準備ワーカーを使い、60秒の履歴から最大ラスタへの変換を測る。3 Overlap、Autoの有無、平均・p95・最大時間を比較する。`cargo test --all-targets`では各条件1回だけ動作確認する。

実時間比較は同じ入力経路・Fs・FFT精度／長・表示寸法でLiveとstressを別々に実行する。`MEASURELAB_PROFILE_SPECTROGRAM=live`はSpectrogram単独・60秒・Autoの比較基準、`stress`は同じ表示からHold／固定時間A／パン／ズーム／色／時間幅／Liveを反復する。条件・世代不変とSTFTの入力／結果／保存欠落なしを判定し、UIフレーム時間、STFT／収集／表示準備時間、ラスタ容量、GPU payload／転送量を出力する。GPU容量はリサイズ時の旧新テクスチャを含み、ドライバー使用量は含めない。

```sh
./scripts/cargo.sh build --release --locked --features qa
MEASURELAB_PROFILE_SECONDS=120 MEASURELAB_PROFILE_SPECTROGRAM=live \
    MEASURELAB_PROFILE_DEMO_BIN_TONE=1 MEASURELAB_PROFILE_SPECTRUM_MODE=continuous \
    MEASURELAB_PROFILE_UI_STALL=1 MEASURELAB_PROFILE_KEEP_AWAKE=1 \
    ./scripts/profile-stage2.sh spectrogram-live --demo
MEASURELAB_PROFILE_SECONDS=120 MEASURELAB_PROFILE_SPECTROGRAM=stress \
    MEASURELAB_PROFILE_DEMO_BIN_TONE=1 MEASURELAB_PROFILE_SPECTRUM_MODE=continuous \
    MEASURELAB_PROFILE_UI_STALL=1 MEASURELAB_PROFILE_KEEP_AWAKE=1 \
    ./scripts/profile-stage2.sh spectrogram-stress --demo
MEASURELAB_PROFILE_SECONDS=120 MEASURELAB_PROFILE_SPECTROGRAM=stress \
    MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" MEASURELAB_PROFILE_SAMPLE_RATE=192000 \
    MEASURELAB_PROFILE_CHANNEL=16 MEASURELAB_PROFILE_KNOWN_OUTPUT=1 \
    MEASURELAB_PROFILE_FFT_SIZE=32768 MEASURELAB_PROFILE_STFT_SIZE=32768 \
    MEASURELAB_PROFILE_SPECTRUM_MODE=continuous MEASURELAB_PROFILE_UI_STALL=1 \
    MEASURELAB_PROFILE_KEEP_AWAKE=1 \
    ./scripts/profile-stage2.sh spectrogram-blackhole16-stress
```

Overlapを比較するときは`MEASURELAB_PROFILE_STFT_OVERLAP=50`／`75`／`87.5`を両条件へ同じ値で指定する。既定は75%。

内部の既知正弦波には`MEASURELAB_PROFILE_DEMO_BIN_TONE=1`を追加する。外部I/Oでは`--demo`を外し、`MEASURELAB_PROFILE_DEVICE`・`SAMPLE_RATE`・`CHANNEL`を共通接頭辞付きで指定する。BlackHoleでは`MEASURELAB_PROFILE_KNOWN_OUTPUT=1`で仮想デバイスへの既知信号出力・既存Spectrum照合・出力通知監査を併用できる。内部デモ、Software Loopback、外部I/Oの結果を区別し、利用していない経路の成功へ広げない。ログとRSSは`dist/stage2-qa/`に保存し、数値の合否はログ内のQA判定と欠落を確認する。画面スリープを避ける実行では`MEASURELAB_PROFILE_KEEP_AWAKE=1`も指定する。描画が遮蔽された実行のUI時間を前面表示の性能へ代用しない。

MVPの基本受け入れと、長時間・他の高負荷操作への耐性を分ける。撮影操作が重なった過去の実行では、長いGUI更新間隔、STFT転送とGenerator内部入力の欠落を観測している。起動時に取得キューを一括排出するとSTFTの旧16,384サンプル分のキューが先に飽和するため、取得キューの上限と端数ブロックを受けられる固定容量へ変更した。QA撮影受信後のPNG保存もGUI外へ分離した。通常ビルドの包括的な手動操作と実モニター間DPIは、上記の対象環境に限って確認する。

撮影を伴う比較は`qa_spectrogram.py`へ`--screenshots`を追加する。GPU読み戻しとPNG保存を約1秒ごとに反復し、完了した保存数も合否へ含める。直接profileを起動する場合は`MEASURELAB_PROFILE_SCREENSHOT=repeat`を使う。`STFT transport`はキューの最大使用ブロック数と初期化時間、撮影ログはGUI外での保存時間を記録する。実GPU読み戻し待ち・OS全体の停止とPNG保存を区別し、過去の長いGUI停止やGenerator入力欠落をこの修正だけで解決済みにしない。UAC-232の192 kHzは機器を接続して起動と、入出力停止・ストリーム解放後の再接続を再確認する。

高Fsの反復操作は、欠落なしだけでUI応答の受け入れにしない。Liveとの差、GPU転送量、UI更新間隔と操作感を確認する。意図したUI停止時間を最大フレーム間隔の退行と取り違えず、取得・FFT窓の欠落と表示更新の省略を区別する。

### Cepstrogramの検証

数値定義と合否は`src/cepstrum.rs`の独立DFT／逆DFT・2インパルス・ゲイン・極小値・無音／無効・倍音＋雑音のテスト、`tests/cepstrogram.rs`の全窓長・窓関数・Overlapと実ワーカー／履歴の回帰を正本とする。負のピーク・時間縮約・0番目と無効状態のAuto除外・ケフレンシー範囲は`src/spectrogram/viewport.rs`、旧設定の移行・拒否は`src/settings.rs`に置く。容量テストは旧新モードのHold・選択行・ラスタ・結果プール・FFT scratchを含め、従来のCPU上限内で終了時解放まで確認する。

```sh
./scripts/cargo.sh test --locked --no-default-features --lib cepstr
./scripts/cargo.sh test --locked --no-default-features --test cepstrogram
./scripts/cargo.sh test --locked --no-default-features --test spectrogram_capacity -- --nocapture
./scripts/cargo.sh run --locked --profile dev-fast --features qa -- --gpu-smoke
MEASURELAB_UI_SMOKE_CEPSTROGRAM=1 ./scripts/cargo.sh run --locked --profile dev-fast --features qa -- --ui-smoke
```

GUI QAは実モード選択・停止中の予約・f64適用とf32設定保持・カーソルの独立・Spectrum連動拒否・通常幅／狭幅を自動操作で確認する。GPU読み戻しは実STFT→履歴→表示準備→描画を通し、符号が逆で等しい絶対値の係数、0番目の除外、NoSignalの中立色、NonFiniteの縞を確認する。内部・有限入力の成功をSoftware Loopback・仮想I/O・物理系の精度や長時間Liveの受け入れへ代用しない。

`benches/spectrogram.rs`は同じFs・16ch中の選択1ch・窓長・Overlapで両モードを比較し、追加の対数／逆FFT時間、収集・表示準備の平均／p95／最大、欠落と容量を出力する。`cargo test`は各条件1回だけ、反復性能評価は理由を示して`cargo bench --locked --no-default-features --bench spectrogram`を実行する。

C4の実時間比較は`qa_spectrogram.py --analysis both`で、同一バイナリ・入力・Fs・窓長・OverlapのSpectrogram／Cepstrogramを直列に動かす。各モードのLiveを独立した基準にし、stressでHold・時間選択・パン・ズーム・色・時間幅・Liveを反復する。両方で1秒のUI停止中の解析継続と有限Stop後の独立数値照合を行う。Spectrogramは追加の対数／逆FFT時間が0であることも判定する。

代表48 kHz・選択1ch・全窓長／Overlapの基本実行表は次の72条件とする。最適化済みバイナリは実時間の欠落と表示応答を測るために必要で、同じRustソース・機能構成の検証済みバイナリがあれば再利用する。測定中はビルド・ベンチ・別の音声QAを並行実行しない。

```sh
./.venv/bin/python scripts/qa_spectrogram.py --analysis both --basic --sample-rate 48000 \
    --route demo-50 --route demo-75 --route demo-87_5 \
    --stft-size 1024 --stft-size 2048 --stft-size 4096 \
    --stft-size 8192 --stft-size 16384 --stft-size 32768 \
    --output dist/cepstrogram-c4-matrix
```

`--stft-size`は繰り返し指定でき、省略時は従来の窓長を使う。`--sample-rate`も省略時は各経路の既定値を維持する。ログ・RSS・ソース／バイナリ識別は`manifest.json`へ保存し、`comparisons`は同じ表示操作条件の両モードについてUI／表示応答のp95・最大、フレーム容量・ピークRSS、表示準備時間、1行当たりのSTFT・追加対数／逆FFT・収集CPU時間の差を示す。片側の失敗を比較成功とせず、既存manifestのある出力先は再利用しない。`--audit`は各ケースのモードで数値照合のマーカーを検査し、予定条件が揃わない実行表や受け入れ時間未満の試運転を合格にしない。判定の回帰は`scripts/test_qa_spectrogram.py`に置く。

120秒以上のSoftware Loopbackなどの連続比較は、別の出力先で`--basic`を外して行う。CPU競合・高Fs・入力16ch・仮想／物理経路の限界条件は基本実行表と分け、未実施条件を検証済みにしない。既存のSpectrogram profileへ`MEASURELAB_PROFILE_CEPSTROGRAM=1`を加えて単独実行する入口も維持する。

### Spectrogramの追加手動確認

MVP基本受け入れとは別に、操作可能な環境のQAなし通常ビルドで、通常幅・最小幅付近・倍率変更に対して次を確認する。現在のIntel Macはこの手動確認の対象外とする。自動イベント・画像検証の成功を手動確認済みへ読み替えない。

1. Software Loopbackを開始し、色・Min／Max／Auto・周波数ズーム／パン・Time Rangeを操作する。カラーバー・単位・主要値と共通入力の状態を読めることを確認する。
2. Hold中に時間をスクロールし、測定が続くこと、時間A／Bが勝手に移動しないこと、Liveで最新へ戻ることを確認する。
3. Split view with…からSpectrumを並べ、時間A／Bと独立した周波数カーソルを操作する。Normal Spectrum・Undo・Liveで通常表示へ戻り、表示対象と入力停止操作を見失わないことを確認する。
4. 取得中と停止中にOverlapを変更し、旧履歴の解除と次回Start用の編集を区別できることを確認する。

異なるネイティブDPIの実モニター間での移動は、用意できた環境で別に確認する。1画面の倍率変更で代用しない。

### GUI QAの環境変数

主要なGUI選択（詳細な選択肢は`src/app.rs`の同名環境変数を参照）:

| 環境変数 | 確認すること |
| --- | --- |
| `MEASURELAB_UI_SMOKE_SETTINGS`／`VIEW`／`ADJUST` | 共通入出力画面・単独／コンソール表示・選択中の詳細。`VIEW=scope`／`spectrum`／`spectrogram`／`xy`／`lockin`／`comparison`／`generator`で単独、`all`は4区画、`console`は7計器、`empty`は空コンソール。`DETAILS=1`は狭幅の詳細編集。変数名の共通接頭辞は`MEASURELAB_UI_SMOKE_` |
| `MEASURELAB_UI_SMOKE_INTERACTIONS=1` | 実際のshellウィジェットを使ったクリック・キー・狭幅・倍率・模擬native scaleの状態遷移。音声ランタイムを重複生成しない |
| `MEASURELAB_UI_SMOKE_SCOPE_FLOW=held`／`waiting`／`single`／`error`／`error-empty` | `IDLE=1`と併用し、実ウィジェットからSoftware Loopbackを取得する通しQA。指定した状態まで進めて撮影。`POINTER=inside`／`outside`でScopeのポインターを固定し、縦ガイド線を比較 |
| `MEASURELAB_UI_SMOKE_SCOPE_GENERATOR_VIEWS=1` | `GENERATOR=scope`と併用し、通常Generatorの内部接続を動かしたままScope・複数計器・狭幅・倍率変更の独立性を照合 |
| `MEASURELAB_UI_SMOKE_LAYOUT=columns`／`rows`／`grid`／`tabs` | コンソールの希望配置。タブ列の折り返し後の残り寸法で退避を判断し、描画と同じ区画寸法で検証 |
| `MEASURELAB_UI_SMOKE_SPECTROGRAM_DISPLAY=1`（`pair`で連携表示を撮影） | Spectrogramの色・Auto・時間幅の実ウィジェット、ホイールズーム、横／縦パン、Shift＋ホイール、Hold／Live、f64実フレーム固定、カーソル線ドラッグ、ダブルクリック、Pairの時間A／B Spectrum・f64値・通常結果維持・独立周波数カーソル・出力ガードとScope出力・Undo／解除、停止中のOverlap編集、狭幅・模擬DPI。表示操作でSTFT条件・世代・出力コマンド不変 |
| `MEASURELAB_UI_SMOKE_SPECTRUM4=1` | 内部4chスペクトルの重ね表示・共通軸・下部CHバー。物理4ch入力の確認ではない |
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

GeneratorのUI停止はRUNNING・遷移外・1秒分以上のPCM進行後に行い、入力・出力・解析の継続をそれぞれ判定する。有限Stop、独立数値照合、ストリーム／通知リスナー解放後の通知監査までを必要とし、途中終了・ログの欠落0だけで合格にしない。USB抜去を伴う試験は実施しない。

Spectrum遅延は同じ結果群の入力利用可能→解析完了→UI提出をCPU時刻で直接集計する。p95の合計・差は使わず、ADC取得時刻・GPU完了・scanout・窓充填／平均整定とは区別する。コールバック計測はプリエンプション込みのホスト経過時間で、厳密なスレッドCPU時間ではない。QA計測の追加メモリ・転送負荷も条件へ含める。

反復性能は`cargo bench --locked --no-default-features`で測る。`cargo test`によるbench各条件1回は動作確認で、性能判定には使わない。

## 配布パッケージの受け入れ

公開候補と同じソースSHA・通常release／desktop・qaなしの配布実行ファイルを使う。以下は未実施の手順であり、過去の開発QA・CIのパッケージ検証を合格へ代用しない。公開操作は [公開準備](RELEASE_PREPARATION.md#公開候補の通し確認と公開運用) に分ける。

手動GUI操作に関する行は操作可能な環境に適用する。現在のIntel Macでは上記の環境除外に従い、手動GUI操作を未完了条件に数えない。配布実行ファイル・実入出力・保存データの検証と、手動操作の対象外を分けて判定する。

| 段階 | 確認内容 |
| --- | --- |
| 識別 | 配布ファイル名・SHA-256、build-infoのソースSHA・版・対象CPU・機能、展開後／コピー後の実行ファイルSHA-256を記録する |
| 起動 | インストール／展開後の通常GUIを起動し、Scope単独、入力・出力停止、I/O・Help・計器選択、通常幅／狭幅の操作を確認する |
| 内部経路 | Software Loopbackの取得→完全窓→停止→数値確認、Generator内部出力と入力の独立Start／Stop、Scope／Spectrum／Lock-in／同期比較の有効性・保持を確認する |
| 実入出力 | 使用機器・配線・公称Fs・CH・PCM・バッファ・未校正条件を記録し、REF／応答を観測する。音声通知・欠落・整定・失敗を正常値へ置き換えない |
| Generator | 周波数・peak振幅・位相の編集、入力Stop時の出力継続、出力Stop、設定復元・別プロセス復元後のOFFを確認する。再接続は入出力停止・ストリーム解放後に限り、明示Start後の再測定を確認する。ERROR処理は模擬条件で別判定する |
| 同期比較 | 異なるREF／SIG、既知ゲイン・位相の照合、低REF／欠落時の無効化、有限Stopと条件付きJSON／CSV・参照比較を確認する。独立数値照合は既存の機能別QAを参照する |
| 保存・再起動 | Fileで設定v9と保持JSON v6・CSV・対象PNGを保存し、アプリ終了後に同じ配布物を再起動する。停止中の設定復元、出力OFF、参照JSON読込、明示Start後の再測定と条件一致を確認する |
| 負荷と表示 | 通常GUIの手動操作、実モニター間DPI、反復起動・再接続・長時間を条件別に判定する。既知の高負荷GUI停止・STFT／Generator欠落の再現条件と未確認条件を区別する |

OS別には次を追加する。

* Windows：配布するMSVC releaseのSetup／ZIPを使用し、ユーザー単位の導入とマイクアクセス、通常GUI・実入出力・保存復元を確認する。GNU／dev-fast VMの過去の起動を配布版の結果にしない。
* Linux：AppImage／tar.gzの同じAppDirで実入出力・保存復元を確認する。FUSEあり／なし、X11／Wayland、実GPU、再接続・長時間はそれぞれ条件を残す。
* macOS：Intel／Apple Silicon各DMGからコピーしたアプリをFinderで起動する。初回マイク許可、拒否、設定変更と再起動後の復帰、実入出力・保存復元を確認する。TCC操作は利用者が行い、ターミナル起動の権限で置き換えない。

証拠はGit管理外の`dist/package-acceptance/<SHA>/<OS-CPU>/`に保存する。manifestには候補SHA、配布物／実行ファイルのハッシュ、OS版・CPU・GPU・表示サーバー、機器と配線・Fs・CH・PCM、試験名、pass／fail／not-run、保存先・ログ・画像、既知の制限を残す。短い実機確認の結論だけを下記の要約へ反映し、未実施や以前の成功を現在の受け入れとして追加しない。

## コードで代替できない確認の要約

### Windowsネイティブでの開発環境と起動確認

`a98a7d31`のRustソースを、Windows 10 Pro（10.0.19045 x64）／Apple iMac15,1・Core i5-4690・4論理CPU・32 GiB RAMで確認した。Rust 1.99.0のMSVC、Visual Studio Build Tools 2022 17.14.42／Windows SDK 10.0.26100.0、`dev-fast`・既定`desktop`・`qa`なしで`--help`、`--gpu-smoke`、通常GUI（`--compact`）のウィンドウ生成が成功した。GPU読み戻しは`Dx12 · AMD RADEON R9 M290X`（ドライバー15.200.1060.0）を使用した。この環境のハードウェア描画確認であり、測定性能の受け入れではない。ZOOM UAC-232と内蔵マイクの入力列挙も成功したが、入出力ストリームは開始していない。実画面のクリック操作、DPI切り替え、保存復元、長時間動作と配布パッケージは未確認。環境・バイナリSHA-256・起動／描画ログはGit管理外の`dist/windows10-native-setup/`に保存する。

`80e8c54e`のRustソースを、Windows 11 Pro（10.0.26300 x64）のネイティブ起動／Apple iMac15,1・Core i5-4690・4論理CPU・32 GiB RAMで確認した。Rust 1.99.0の`x86_64-pc-windows-msvc`、Visual Studio Build Tools 2022 17.14.42、Windows SDK 10.0.26100.0を導入し、`dev-fast`・既定`desktop`・`qa`なしでビルドした。[MSVC手順](WINDOWS.md#msvcでのセットアップ)に従い、GNU／LLD用の追加指定なしで`--help`、`--gpu-smoke`と通常GUI（`--compact`）のウィンドウ生成を確認した。ZOOM UAC-232の入力デバイス列挙も成功したが、入出力ストリームは開始していない。

同じRustソースの`dev`・`qa`ビルド（デバッグ情報・インクリメンタルなし）で`--ui-smoke`も成功し、7計器の移動・構成変更の自動検証と、停止・保持中の2ch QA波形のPNGを確認した。実デバイスの入力取得・信号出力は実施していない。

表示ドライバーはMicrosoft基本ディスプレイアダプターで、読み戻しと自動UI検証は`Dx12 · Microsoft Basic Render Driver`を使用した。Vulkanドライバーなし・OpenGL 1.1の診断も出たが、Dx12の検証は終了コード0で完了した。ネイティブ起動でもソフトウェア描画の確認であり、iMacのGPUによるハードウェア描画の受け入れではない。画面内の手動操作、OpenGL、実音声入出力・測定精度、保存復元、DPI切り替え、負荷・長時間動作、配布パッケージの受け入れは未確認とする。環境・バイナリSHA-256・起動／描画ログとQA画像はGit管理外の`dist/windows-native-setup/`に保存する。

### Windows VMでの起動確認

`7a7df79a`のソースを、Windows 11 Pro（10.0.26300 x64）／VMware20,1・2論理CPU・4 GiB RAMで確認した。Rust 1.99.0の`x86_64-pc-windows-gnu`、LLVM-MinGW 20261006の`llvm-dlltool`／LLDを使用し、`dev-fast`・既定`desktop`・`qa`なしでビルドした。[再現手順](WINDOWS.md) に従う通常GUI（`--compact`）のScope初期画面、入力・出力停止、Helpの開閉を確認した。

描画は`Dx12 · Microsoft Basic Render Driver`で、OpenGL指定は不要だった。表示ドライバーはMicrosoft基本ディスプレイアダプターで、VMwareのハードウェア3D描画を受け入れた結果ではない。`--gpu-smoke`も同バックエンドで成功した。GNU既定リンカーの生成物は`--help`でも`0xC0000005`で終了したため、LLDを明示する。アプリのソース変更は不要だった。

ローカル証拠は`dist/windows-startup-qa/`の環境・バイナリSHA-256・ビルド／描画ログ。確認範囲は起動と基本的な画面応答に限る。MSVC版、release版、OpenGL、音声入力・出力、測定精度、保存復元、DPI切り替え、負荷・長時間動作は未確認とする。

### Linux AppImageでの起動確認

`2a50cd95`のソースをUbuntu 22.04.5のクラウドrunner・Rust 1.99.0で通常release・`desktop`のみ・`x86_64-unknown-linux-gnu`としてビルドしたAppImageを、Ubuntu 26.04.1 x86_64／X11で確認した。AppImageをFUSE経由で直接起動し、`--compact`の通常ウィンドウ生成を確認した。

Intel Iris Pro Graphics 6200（BDW GT3）／Vulkanで同じ配布実行ファイルの`--gpu-smoke`が成功した。これは既知の内部データによるGPU読み戻しであり、物理音声経路の測定確認ではない。ローカル証拠は`dist/linux-package-qa/manifest.json`、`final-verification.log`、`final-gui.log`と配布物のbuild-info。実入出力、測定精度、通常GUIの包括的な操作、保存復元、DPI切り替え・再接続・長時間動作は未確認とする。

### macOSでの測定・GUI確認

共通環境はmacOS 14.8.9・x86_64・Rust 1.99、GUIはMetal／AMD Radeon R9 M290X。Fsは公称、入出力FS・物理時計・CH間校正は未校正。差分を記した行は基点SHAの上の作業差分が対象であり、SHAだけを検証済みソースとしない。現在のIntel Macの手動GUI操作は上記の計画除外に従う。

| 対象・基点／条件 | 確認した範囲と制限 |
| --- | --- |
| Spectrogram S6、`514ff17a`＋S6差分／release QA・内蔵5K・native scale 2.0 | MVP基本受け入れを完了。内部デモ3 Overlap、Software Loopback・通常Generator内部入力・BlackHole 16chの192 kHz、BlackHole 2ch・UAC-232の48 kHzでLive／反復操作・UI停止中の継続・独立数値照合を確認。UAC-232はL-L TRS、R-Rは−20 dBアッテネーター付きXLR。証拠は`dist/spectrogram-s6-basic/manifest.json`の内部／BlackHoleと`dist/spectrogram-s6-basic-uac48/manifest.json`。単独／Pair・通常幅／狭幅の画像とイベントは`dist/spectrogram-s6-ui/`・`dist/spectrogram-s6-ui-measurement/`。通常ビルドの包括的手動操作・実モニター間DPIは未確認 |
| 同S6で観測した制限／高負荷・物理192 kHz | 撮影操作が重なった長時間評価でGUI更新の長い停止、STFT転送とGenerator内部入力の欠落を観測。失敗・中断は`dist/spectrogram-s6/manifest-audited.json`等に保存。UAC-232の192 kHz起動時のSTFT転送欠落は`dist/spectrogram-s6-basic/`・`dist/spectrogram-s6-basic-uac-recheck/`で不合格。下記の修正後も物理192 kHzは再確認が必要で、48 kHzや仮想入力の成功で置き換えない |
| Spectrogram負荷修正、`f06d68946`＋修正差分／release QA・Metal Intel Iris Pro 6200・native scale 2.0 | BlackHole 16ch・192 kHzの入力専用起動でSTFT転送欠落を再現し、修正後は同条件で欠落なし。Software Loopback・通常Generator内部入力・BlackHole 16chの192 kHzで反復撮影を含むLive／表示操作、Generatorでは各120秒、独立DFT・UI停止中の継続・有限Stopを確認。I/O統合操作・単独／Pair表示・Generator操作・GPU読み戻しも確認。証拠は`dist/spectrogram-stall-fix/`の`baseline.json`、`repeat-basic/manifest.json`、`generator-120/manifest.json`、`gui/manifest.json`。UAC-232は接続できず未実施。過去の長いGUI停止・Generator入力欠落は今回再現せず、他負荷・物理系を含む解決判定は残る |
| GUI G4、`32ec3f5d`＋G4差分／dev QA・native pixels per point 2.0・画面スリープ抑止 | 7計器、単独／コンソール・4区画・狭幅・倍率・詳細・入出力画面の画像を確認。内部経路とBlackHole 2ch／16ch・48 kHz・f32の通常Generator、独立Lock-in／比較照合、UI停止中の継続、有限Stop、保持・JSON／CSV・OFF復元・別プロセス再測定を確認。背面固定ではMetalの`Occluded`と撮影タイムアウト、前面保持では撮影成功を再現した。ソース／バイナリ識別・ログ・画像は`dist/gui-redesign-g4-acceptance/manifest.json`、遮蔽の比較は`dist/gui-capture-diagnosis/occlusion/`。通常ビルドの手動操作・実モニター間DPI切り替えは未確認 |
| UAC-232統合QA、`4741b5dc`／release・desktop + qa、48 kHz・2ch・f32・L-L TRS／R-R XLR（−20 dB）・1,024 frames | 通常Generatorの同じ生入力窓の独立Lock-in／同期比較DFT照合、独立Stop、保持・JSON／CSV／PNG・別プロセス復元・OFF復元・再測定、Singleの生入力照合を確認。固定信号の保存QAは宣言した接続待機区間に通知1件、測定区間0件。GUIなしのLock-in QAはREF消失／不安定REF・CH交換・二段EMA・転送飽和後の無効化と回復まで通過。小信号の位相変化は原因未確定。ソース／バイナリ識別と証拠は`dist/package-acceptance/4741b5dce794e6007962b2438972a85fb8f7f9a9/macos-x86_64/uac232-20261019/manifest.json`。同じソースの既存ビルド・Rustチェック・内部／BlackHole QA・DMG検証はハッシュ照合して再利用し、重複実行していない。qaなし配布物・最大Fs・実機再接続は未受け入れ |
| Lock-in、`a837b04c`／BlackHole 2ch・16ch、44.1／48／96／192 kHz | 短時間の数値・欠落回復・保存再測定。2ch・48 kHzはGUIなし600秒、正常測定区間の通知・欠落0。物理精度・通常GUI600秒の保証ではない |
| Lock-in、`1c0373dc`／UAC-232 LL／RR TRS、同4レート | 同じ生入力窓の独立適合・保存再取得。48 kHzはGUIなし600秒、最大R差0.598 µFS peak・位相差0.0004101°。−40 dB応答で高レベル基準から約0.115〜0.155°の位相変化があり原因未確定 |
| 段階4、`60021e3f`／Software Loopback・BlackHole・UAC-232 | 通常幅・狭幅、別プロセス復元・再測定、画像保存。BlackHole 16ch・96 kHz・512k Continuousは30秒、20予定窓・入力／解析欠落0。UAC-232・48 kHzの30秒はUI停止中の継続・有限Stop・独立照合・解放後監査を確認 |
| 同段階4、UAC-232・48 kHz・4表示・512k | 約270秒・95窓・捕捉欠落0までの観測を受け入れ。中断時に入力通知2件、最終有限照合・監査なし。600秒完走の成功ではない |
| 内部Generator、`6c6feaad`／2ch・48 kHz・f64 | 750 Hz・0.125／0.0625 FS peak・+30°、Scope／Spectrum／Lock-in、1秒UI受信停止・独立Stop・JSON／CSV・OFF復元を確認 |
| 通常Generator実出力、`03622c6f`／BlackHole 2ch・16ch・UAC-232、48 kHz・f32 | 750 Hz・0.1／0.05 FS peak・+30°、Scope／Spectrum／Lock-in、独立Stop、JSON／CSV・OFF復元を条件付き確認。通常幅1440×860・狭幅900×660の旧GUI確認で、後の表示変更・DPI切り替えの確認ではない |
| Generator連続評価、`4741b5dc`／同UAC-232配線・release QA・48 kHz・f32・1,024 frames・画面スリープ抑止 | 600秒指定・100編集、入出力通知と取得／Spectrum／STFT入力・結果・履歴保存の欠落0。1秒UI停止中も入出力・FFT・STFT収集が継続し、最終独立Lock-in／比較DFT・保持JSON／CSV・有限Stop・解放後監査まで通過。撮影・並行ビルド・別音声試験なし。最大UIフレーム間隔約29秒を観測し、表示応答の受け入れにはしない。Spectrogramの前面描画は対象外。証拠は上記manifestの`generator-600`とcallback report |
| 廃止した実USB切断試験の過去記録、`83a0421b`／UAC-232・48 kHz・2ch・f32・dev QA | ERROR保持・入力停止・出力解放、再接続と同じ出力条件の復元でOFFを観測。安全制約により今後の抜去試験・反復抜去は実施しない。停止・解放後の安全な再接続と明示Start後の再測定は別に未確認 |
| 同期比較、`83a0421b`／Software Loopback・48 kHz・750 Hz、N=4,096・平均4 | ゲイン0.5・+30°、CH交換で2.0・−30°、有限Stop・保存・OFF復元・再測定を確認。この旧SHAの結果を現行版の受け入れへ代用しない |

CoreAudioの起動／再接続XrunはBlackHole・UAC-232で発生した。バッファ要求変更後の上記UAC-232成功は全起動・他Fsの保証ではなく、初期試験の操作介入の可能性と原因は未確定。接続直後のSingle・外部可変callback・物理16ch・他OS／機器・実時計／物理校正・GPU実行／実表示遅延は確認を残す。

詳細な旧記録は [整理前のGit履歴](https://github.com/youtube-at-vach/MeasureLab/tree/61b36dc3/guide/rust/validation) で必要時だけ参照する。ローカル証拠は`dist/stage4-macos-qa/`、`dist/generator-qa/`、`dist/lockin-physical-qa/`等のmanifest・JSON・ログ・画像で、Git管理外のため新しいcheckoutに存在するとは限らない。新しい実機確認は対象リビジョン／差分・バイナリ識別、環境・条件、判定・失敗・未確認範囲を短く更新し、試行ごとの経過を文書へ追加しない。

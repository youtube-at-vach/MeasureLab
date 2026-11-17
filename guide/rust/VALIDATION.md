# Rust の検証

テスト条件・許容差・合否はコードを正本とする。回帰は該当モジュールの既存テストに追加し、実機の観測だけを[確認の要約](#コードで代替できない確認の要約)に残す。

## 変更に応じた検証

| 変更 | 確認 |
| --- | --- |
| Rustの動作・数値 | [共通チェック](#rustの共通チェック)と影響した経路。取得・Stopは欠落と世代分離、測定式は既知入力、ファイル形式は旧版の読み込みと往復 |
| GUI・文言 | 対象計器・画面の操作と幅。翻訳は[対象言語と画面](I18N.md)を選ぶ |
| I/O・連続性・性能 | 変更が影響する入力経路・負荷を選び、短い試験で再現できない場合に実時間比較を使う |
| 配布・インストーラー | [該当OSのCIと配布物](RELEASE_PREPARATION.md#prの実機検証用artifacts)。初回公開は[公開準備](RELEASE_PREPARATION.md#初回プロトタイプ配布前のタスク)を参照 |
| 開発文書・サイト・CI | Markdown lint、Ruff、変更対象のPythonテスト・actionlint。公開マニュアルとサイトの入力変更は[Pagesビルド](#サイトと静的チェック)も実行 |

## Rustの共通チェック

リポジトリルートで実行する。Windowsは `cargo` または `./scripts/pwsh.cmd -File ./scripts/cargo.ps1` を使う。[CI](../../.github/workflows/ci.yml)では関連変更でRust 1.95も確認する。

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --no-default-features
./scripts/cargo.sh test --locked
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --doc --all-features
```

ベンチは `cargo test` で各条件1回、反復計測は `cargo bench --locked --no-default-features` を使う。ローカルのreleaseビルドは性能・release固有の調査・配布物の確認で必要なときに実行する。

### 開発ビルドと時間計測

日常の起動は `./scripts/debug.sh`（`target/dev-fast/measurelab`）、型・変数を調べる場合は `--full-debug`、性能評価は `--release`。`--demo` と `--ui-smoke` は `qa` を有効にする。

ビルド時間は `./scripts/cargo.sh build --locked --profile dev-fast --timings` を使い、`target/cargo-timings/` を参照する。OS・CPU・Rust・機能構成を揃え、初回は未使用の `--target-dir` を指定し、変更なしと小変更後の計測を区別する。

## サイトと静的チェック

```sh
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx --yes markdownlint-cli2@0.23.3 '**/*.md' '#node_modules'
```

CI変更は `actionlint`、Pythonの回帰は `./.venv/bin/python -m unittest discover -s scripts -p 'test_ci_changes.py'` のように対象を選ぶ。翻訳のPR前チェックは[I18N](I18N.md)を参照する。

```sh
npm --prefix download-site ci
npm --prefix download-site test
./.venv/bin/python scripts/build_pages.py
```

サイト単体のビルドは `npm --prefix download-site run build`。PagesビルドはPython 3.12以降の `.venv` に `requirements-docs.txt` を導入して実行する。新旧MkDocsのstrictビルドとサイト統合、公開URLを確認する。

## 検証対象環境と既存成果物

- ソースSHAと作業差分、構成とバイナリのSHA-256、環境・設定・経路が一致する証拠は再利用する。未確認の経路と環境は明記する。
- 証拠はGit管理外の `dist/`、自動チェックはCIを参照する。過去の詳細は[整理前の検証ガイド](https://github.com/youtube-at-vach/MeasureLab/blob/27887c319bfba4a682c451e22e7780b9572b2766/guide/rust/VALIDATION.md)にある。配布候補の対象環境と担当は[公開準備](RELEASE_PREPARATION.md#公開前の最小確認セット)を参照する。

## 物理デバイスの安全制約

測定・出力中のUSB抜去試験は実施しない。配線・接続の変更は入出力を両方停止し、ストリームの解放を確認してから行う。エラー処理は模擬通知で、停止後の再接続はOFF復元と明示Start後の再測定で確認する。

## テストコードの入口

| 対象 | 正本 |
| --- | --- |
| PCM・CH・Fs・可変callback・取得キュー・有限終端 | [audio.rs](../../src/audio.rs)、[measurement.rs](../../src/measurement.rs) |
| トリガー・Scope統計・Single／Autoset・XY | [acquisition.rs](../../src/acquisition.rs)、[signal.rs](../../src/signal.rs)、[xy.rs](../../src/xy.rs) |
| FFT・窓・独立FFT／Parseval・PSD／ESD・校正 | [spectrum.rs](../../src/spectrum.rs)、[ESDテスト](../../src/spectrum/esd_tests.rs)、[calibration.rs](../../src/calibration.rs) |
| 解析転送・欠落・世代・表示受信停止 | [spectrum_worker.rs](../../src/spectrum_worker.rs)、[stft.rs](../../src/stft.rs)、[負荷テスト](../../tests/analysis_resilience.rs) |
| Cepstrogram・STFT履歴・表示縮約・容量 | [cepstrogram.rs](../../tests/cepstrogram.rs)、[spectrogram_capacity.rs](../../tests/spectrogram_capacity.rs)、[Spectrogramモジュール](../../src/spectrogram/) |
| Generator・出力・優先Stop | [Generatorテスト](../../src/generator/tests.rs)、[output/](../../src/output/) |
| Lock-in・同期比較・同じ入力窓の独立照合 | [lockin.rs](../../src/lockin.rs)、[比較テスト](../../src/comparison/tests.rs)、[物理Lock-in QA](../../src/qa/physical_lockin.rs)、[比較QA](../../src/qa/comparison.rs) |
| 保存互換性・原子的保存・f64往復・不正参照 | [settings.rs](../../src/settings.rs)、[export.rs](../../src/export.rs)、[results.rs](../../src/results.rs)、[file_io.rs](../../src/file_io.rs) |
| 起動オプション・設定自動保存・模擬デバイス | [launch_options.rs](../../tests/launch_options.rs)、[起動設定](../../src/settings/preferences.rs)、[GUIの復元QA](../../src/app/preferences.rs) |
| 実ウィジェットとGPU読み戻し | [gui_qa.rs](../../src/app/gui_qa.rs)、[shell.rs](../../src/app/shell.rs)、[gpu.rs](../../src/gpu.rs) |
| 反復CPU性能 | [benches/](../../benches/) |

個別に確認する例は `./scripts/cargo.sh test --locked --lib --no-default-features measurement::tests`。

## コア解析の負荷耐性QA

[analysis_resilience.rs](../../tests/analysis_resilience.rs)は既知f64入力で、入力転送・取得・Spectrum・STFT履歴・Lock-in・同期比較を同時に動かす。短い回帰は通常のテストに含まれる。CPU競合下の実時間比較が必要な場合は、同一バイナリで両モードを直列に実行する。

```sh
for analysis in spectrogram cepstrogram; do
    MEASURELAB_STRESS_ANALYSIS="$analysis" \
        MEASURELAB_STRESS_SECONDS=120 MEASURELAB_STRESS_RATE=192000 \
        MEASURELAB_STRESS_CHANNELS=16 MEASURELAB_STRESS_COMPETITORS=3 \
        MEASURELAB_STRESS_STFT_SIZE=1024 MEASURELAB_STRESS_OVERLAP=87.5 \
        MEASURELAB_STRESS_REQUIRE_CONTINUOUS=true \
        ./scripts/cargo.sh test --release --locked --no-default-features \
        --test analysis_resilience -- --ignored --nocapture
done
```

無欠落の受け入れでは `MEASURELAB_STRESS_REQUIRE_CONTINUOUS=true` を指定する。限界探索では省略し、欠落の発生箇所・有限Stop・再開後の数値と世代分離を確認する。`ANALYSIS_RESILIENCE` と `ANALYSIS_RECOVERY` のJSONを保存する。この試験の入力は模擬フレームで、音声callbackやGUIの性能は別に検証する。

## GUI・入出力QAの再実行

```sh
./scripts/debug.sh --gpu-smoke
./scripts/debug.sh --ui-smoke
./.venv/bin/python scripts/qa_gui_redesign.py \
    --binary target/dev-fast/measurelab --case widget-interactions
```

[GUI runner](../../scripts/qa_gui_redesign.py)の `--list-cases` で名前を調べ、対象を `--case` で明示する。`widget-interactions` は実ウィジェット、`startup-preferences` は一時ファイルと模擬デバイスでの設定復元、`scope-flow-*` は内部入力の取得・停止・保持を確認する。撮影できない場合は `--assertions-only` と専用の出力先を指定する。macOSの画面撮影では必要に応じて `caffeinate -du` を使い、Metalの `Occluded` はウィンドウの重なりを確認する。

通常Generatorの別プロセス復元は次で内部経路を実行する。保存時の設定・参照JSONを検証し、復元後OFF、明示Start後の再測定、独立Stopと同じ入力窓でのLock-in／DFT照合を確認する。

```sh
./.venv/bin/python scripts/qa_gui_redesign.py \
    --binary target/dev-fast/measurelab --case generator-replay \
    --output dist/generator-restart-qa
```

外部経路は `--device` と対象の `--case` を明示する。保持結果の復元には対応する `held-…-save` と `held-…-replay` を選ぶ。外部Single取得は `scope-blackhole-2ch-single` などの該当ケースを使う。物理QAではL→L・R→Rの配線と減衰を `--connection-note` に記録する。UAC-232のQA出力は最大0.1 FS peak・DCなし。

仮想・物理デバイスの短いCLI確認は `--list-devices`、`--audio-smoke`、`--stft-smoke` を使う（`--channel` は1始まり）。Lock-inの既知信号はQA版の `--lockin-smoke` または `--physical-lockin-smoke` を使い、機器は `--input-device`、試験時間は `MEASURELAB_LOCKIN_SECONDS` で指定する。特定のLock-in状態を調べる場合は `MEASURELAB_UI_SMOKE_LOCKIN=ref-loss ./scripts/debug.sh --ui-smoke` のように状態を指定する。

### 多言語基盤（I5）

[src/i18n.rs](../../src/i18n.rs)でフォールバック・設定復元・フォント、[Pythonテスト](../../scripts/test_i18n.py)で翻訳ツール、GUI runnerの `widget-interactions`・`language-demo-controls` で切替後の可読性と測定状態の維持を確認する。翻訳変更は[開発・翻訳手順](I18N.md)の対象差分だけを検証する。

### 全9言語の画面レビュー（I6e）

初回の全9言語レビューは完了済み。確認した画面・条件・結果は[完了時の検証ガイド](https://github.com/youtube-at-vach/MeasureLab/blob/997c512da788264695e754ae3dd8836376747a22/guide/rust/VALIDATION.md#全9言語の画面レビューi6e)を参照する。今後は変更した文言が出る画面と、長い文言が現れる通常幅・狭幅を確認する。GUI runnerには `--locale` と対象 `--case` を指定する。

### Cepstrogramの検証

独立DFT／逆DFTと符号付き係数は [cepstrum.rs](../../src/cepstrum.rs)、全窓長・窓関数・Overlapと実ワーカーは[統合テスト](../../tests/cepstrogram.rs)、CPU容量と解放は[容量テスト](../../tests/spectrogram_capacity.rs)で検証する。表示の確認はGPUスモークと `MEASURELAB_UI_SMOKE_CEPSTROGRAM=1 ./scripts/debug.sh --ui-smoke` を使う。

SpectrogramとCepstrogramの実時間比較は[STFT QA runner](../../scripts/qa_spectrogram.py)で対象の `--analysis` と `--route` を指定する。短い確認は `--basic`（各20秒）、連続性・表示応答の評価は各120秒以上。`--generator-display` の各600秒は、Generator出力に対する表示・撮影負荷を比較するときに使う。

```sh
./scripts/cargo.sh build --release --locked --features qa
./.venv/bin/python scripts/qa_spectrogram.py --analysis both --basic \
    --route software --stft-size 1024 --output dist/stft-comparison
./.venv/bin/python scripts/qa_spectrogram.py --audit dist/stft-comparison/manifest.json
```

UI停止中の継続、有限Stop後の数値、欠落・通知、UI間隔と表示要求からUI適用までの時間を確認する。GPU完了・実表示の遅延は別の指標。仮想／物理出力では接続待機中と測定区間の通知を別に記録し、解放後を監査する。物理試験の配線と減衰は `--physical-connection` に記録する。

## 性能・継続性

[profile-stage2.sh](../../scripts/profile-stage2.sh)で対象条件のログ・CPU・RSSを採取する。設定と入力経路を揃え、ビルドや他の音声試験を止めて比較する。`MEASURELAB_PROFILE_UI_STALL=1` は画面停止時の継続確認に使う。

```sh
MEASURELAB_PROFILE_SECONDS=20 ./scripts/profile-stage2.sh demo-20 --demo
./scripts/cargo.sh bench --locked --no-default-features --bench spectrogram
```

ベンチの反復は `cargo bench` で行う。計測値の定義は [qa.rs](../../src/qa.rs) と[ベンチコード](../../benches/)を参照する。

## 配布パッケージの受け入れ

[公開前の最小確認セット](RELEASE_PREPARATION.md#公開前の最小確認セット)に従い、同じ候補SHA・通常release／desktop・qaなしの配布実行ファイルで短く通す。

1. 配布ファイルと展開後の実行ファイルのSHA-256、build-infoのソースSHA・版・CPU・機能を記録する。
2. インストール／展開後の起動と停止状態を確認する。内部経路と対象機器で、測定→独立Stop→[設定と結果の保存](README.md#保持結果の書き出し)→別プロセスでのOFF復元→明示Start後の再測定を行う。
3. macOSではDMGからコピーしたアプリをFinderで開き、マイク許可は利用者が行う。WindowsはMSVCのSetup／ZIP、LinuxはAppImage／tar.gzの配布物を識別して結果を記録する。手動GUIとDPIは実施範囲を記録する。

証拠は `dist/package-acceptance/<SHA>/<OS-CPU>/` に置く。manifestにはハッシュ、OS・CPU・GPU、機器・配線・Fs・CH・PCM、結果・ログ・未実施条件を記録する。

## コードで代替できない確認の要約

### v0.10.0 配布候補の確認

候補 `c984de4f` の通常release／desktop（qaなし）で、Windows x64 Setup／ZIP、Linux x86_64 AppImage／tar.gz、macOS Intel／Apple Silicon DMGの候補SHAとSHA-256を照合した。[候補ビルド](https://github.com/youtube-at-vach/MeasureLab/actions/runs/42605390842)ではWindowsのインストール・修復・削除、Ubuntu 22.04／24.04／26.04での起動・ソフトウェアVulkan描画、macOSバンドルの起動を確認した。[必須CI](https://github.com/youtube-at-vach/MeasureLab/actions/runs/42604022870)も通過した。

- macOS 14.8.9／Intel Macで、同じ配布アプリのMetal描画、UAC-232のCLI取得とSTFT窓順序（48 kHz・2ch、2秒、欠落0）を確認した。
- 同アプリのGenerator内部ループバック（48 kHz・2ch・f64、1 kHz、−20／−26 dBFS peak）で、同期比較のゲイン0.5012・位相約0°・コヒーレンス1、独立Stop、JSON／CSV保存と別プロセスでのOFF復元・再測定を確認した。
- BlackHole 2chのGUIではマイク許可未完了時に入力開始が `Unknown property` で失敗し、出力停止と通常終了が完了せずプロセスを終了した。許可後のBlackHole、UAC-232のGUI往復、他OSの実入出力、最終配布資産との一致は未確認。証拠は `dist/package-acceptance/c984de4fb1c7eb7f59389304607c577d50a240f3/`。

### macOSでの測定・GUI確認

| 対象 | 確認した範囲と残る制限 |
| --- | --- |
| Generator・同期2chの再起動 | `3fb08798`＋QA差分、Intel Macのdev-fast QA、48 kHz。内部・BlackHole 2ch／16ch・UAC-232（LL TRS／RR XLR −20 dB）でOFF復元、再測定、同じ入力窓の独立照合を確認。UAC-232の停止・解放後の再接続は `71601722`＋QA差分で別に確認。証拠は `dist/generator-restart-20261108/` と `dist/generator-comparison-uac232-reconnected-20261104/` |
| Generator表示負荷 | `71601722`＋QA差分、Intel Macのrelease QA、UAC-232 48 kHz・2ch・f32。各600秒の非表示／Live／反復撮影で取得・Spectrum・STFTの欠落0。実表示遅延は未確認。証拠は `dist/generator-uac232-display-600-20261104/manifest-audited.json` |
| STFTの両モード | `278c160c`＋QA差分、Intel Macのrelease QA。Software LoopbackとBlackHole 16ch（192 kHz）、UAC-232（48 kHz）で各120秒の数値・欠落・応答を確認。S6ではUAC-232の192 kHz起動直後にSTFT欠落があり、負荷修正後の物理192 kHzは未確認。証拠は `dist/cepstrogram-c4-response-routes/`、`dist/cepstrogram-c4-response-uac48/` と `dist/spectrogram-s6-basic-uac-recheck/` |
| 高Fs・CPU競合 | Intel Macのrelease・GUIなし。768 kHz・16chの模擬入力で、Cepstrogram実行時に共通取得の欠落を観測。取得キューの分割返却との比較は `dist/capture-drain-contention/manifest.json`、従来の上限探索は `dist/cepstrogram-contention-qa/manifest.json` |
| 物理Lock-in | `1c0373dc`、UAC-232 LL／RR TRS、44.1／48／96／192 kHzで生入力窓との独立照合。48 kHzのGUIなし600秒を確認。小信号の位相変化の原因、物理振幅・実時計の校正は未確認。証拠は `dist/lockin-physical-qa/` |

高負荷での長時間GUI停止、起動／再接続時のCoreAudio通知、物理4〜16ch・実モニター間DPI・実表示遅延は、関連変更時に[後続の課題](../CURRENT_DIRECTION.md#後続の課題)に沿って扱う。

### Windowsネイティブでの開発環境と起動確認

Windows 10の `a98a7d31` とWindows 11の `80e8c54e` をMSVC・dev-fast・qaなしで確認した。iMac15,1で `--help`、`--gpu-smoke`、通常GUIのウィンドウ生成、UAC-232の列挙に成功した。Windows 11の描画はMicrosoft Basic Render Driver。実入出力と配布物の受け入れは別途確認する。

### Windows VMでの起動確認

`7a7df79a` のWindows 11／VMwareで、GNU＋LLDのdev-fast・qaなしの起動とソフトウェアDx12描画を確認した。GNU既定リンカーの生成物は `0xC0000005` で終了した。[GNU／LLD手順](WINDOWS.md)を参照する。

### Linux AppImageでの起動確認

`2a50cd95` の通常release AppImageをUbuntu 26.04.1 x86_64／X11でFUSE起動し、ウィンドウ生成とIntel Iris Pro Graphics 6200／VulkanのGPU読み戻しを確認した。実入出力・測定・保存復元は未確認。

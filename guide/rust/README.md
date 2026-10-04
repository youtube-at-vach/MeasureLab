# MeasureLab — Rust Audio Measurement Lab

CPALで実際のオーディオ入力を取り込み、`wgpu`で波形とFFTスペクトルを同時に描画するデスクトップ測定ワークスペースです。最終イメージへ向けた段階的な拡張計画は [PLAN.md](PLAN.md) にまとめています。

## 起動

Rust 1.95以上と各OSのビルドツールが必要です。開発・検証にはRust 1.99を使用しています。

```sh
cargo run --release
```

この作業環境ではプロジェクト専用のRust環境を`.tools/`に用意しています。通常の`cargo`がPATHにない場合も、次のコマンドで起動できます。

```sh
./scripts/cargo.sh run --release
```

入力デバイスを選択して **Start input** を押してください。停止すると最後の波形が保持されます。再開時は新しい入力で履歴を作り直します。音声ファイルへの保存やオーディオ出力は行いません。

マイクを使わず試すには、内部信号で起動します。起動後も左側の **Demo signal / Audio input** で入力を切り替えられます。

```sh
./scripts/cargo.sh run --release -- --demo
```

`--compact`を追加すると、上下にプロットを配置する小さなウィンドウで起動します。

デモでは周波数、振幅、ノイズを変更し、正弦波／高調波付き正弦波／帯域制限した矩形波を比較できます。CH 2はCH 1と位相・振幅が異なる信号です。デモ信号は内部だけで使い、スピーカーには出力しません。

開始／停止は上部に固定しています。左の **Settings** は **Input source / Oscilloscope / Spectrum analyzer / Workspace & help** のアコーディオンで、一つの項目を開いて設定します。閉じた項目にも現在値を表示します。各グラフの **Settings** を押すと、その設定を開いて該当位置へ移動します。

グラフ上部の **Settings** で左パネルを非表示にでき、境界をドラッグすると幅を変更できます。**Collapse all** ですべての項目を閉じられます。**Workspace & help** では二画面の配置を **Automatic / Side by side / Stacked** から選択し、ショートカットと測定単位を確認できます。幅が不足する場合は左右指定でも上下に配置します。開閉や配置指定は現在のセッション内で保持します。

macOSではマイクへのアクセスを許可する必要があります。許可がない場合は「システム設定 → プライバシーとセキュリティ → マイク」で、起動に使うアプリ／ターミナルを確認してください。独立したアプリとして起動するには以下を使います。

```sh
./scripts/bundle-macos.sh
open dist/*.app
```

LinuxではALSAおよびウィンドウシステムの開発ライブラリが必要です。Ubuntuの場合:

```sh
sudo apt-get install build-essential pkg-config libasound2-dev libxkbcommon-dev libwayland-dev libx11-dev libxrandr-dev libxi-dev libxcursor-dev
```

WindowsではRustのMSVCツールチェーンとVisual Studio C++ Build Toolsを使用します。

## 操作

| 操作 | 内容 |
| --- | --- |
| Input source / Refresh devices | CPAL入力デバイスの選択・再取得 |
| Start input / Stop / Space | 入力開始・停止 |
| Horizontal / ホイール | 時間軸の変更（0.05〜100 ms/div） |
| Vertical / Shift＋ホイール | 振幅の変更（0.001〜0.5 FS/div） |
| Fit amplitude | 現在の表示振幅に合わせる |
| CH 1 / CH 2 | 最初の2入力チャンネルの表示切り替え |
| Trigger | フリーラン／立ち上がり／立ち下がり、ソースと閾値の設定 |
| ダブルクリック | 時間軸と振幅を初期値へ戻す |
| Scope + Spectrum / Oscilloscope / Spectrum | 同時表示／単独表示。広い画面では左右、狭い画面では上下に配置 |
| 各グラフのSettings | 対象の設定を左パネルで開く |
| グラフ上部のSettings / Collapse all | 左パネルの表示切り替え／設定項目をすべて閉じる |
| Workspace & help | 配置の指定、ショートカット、測定単位 |
| Spectrum Source / points / Window | FFTの入力CH、サイズ（1,024〜32,768点）、窓関数 |
| Power average / Remove DC | 線形電力の指数平均、FFT前の平均値除去 |
| Log Hz / Linear Hz / Span | 周波数軸と表示する上限周波数 |
| Floor dBFS / Peak hold / Clear hold | 表示下限、最大値の保持、保持値のクリア |
| スペクトル上にマウスを置く | 最寄りのFFTビンの周波数と振幅 |

画面は横10分割・縦8分割です。トリガーは横20%位置で、交差が見つからない場合は最新の波形を表示するAuto動作です。RMS・Peak・P-Pは表示範囲の実サンプルから計算します。モノラルデバイスではCH 2を無効にします。3チャンネル以上のデバイスでは最初の2チャンネルを表示します。

振幅はCPALから取得したデジタル音声のフルスケール（FS）です。電圧への換算、外部ADCの制御、音声デバイス以外の入力は未実装です。サンプルレートはデバイス既定の設定を使用します。

スペクトルは片側ビン振幅のdBFSです。窓のcoherent gainを補正し、ビン中心の1 FS peak正弦波を0 dBFSとします。DCとNyquistのビンは2倍しません。PSDやdBmではありません。**Δf** はFs/N、**RBW** は窓の等価雑音帯域です。48 kHz・8,192点・HannではΔf ≈ 5.86 Hz、RBW ≈ 8.79 Hz、窓時間 ≈ 170.7 ms。ピークは最大ビンの値なので、1 kHzの信号が1002.0 Hzのビンに表示される場合があります。

ビンの間にある信号は複数のビンに分散するため、ピークの読み値が実振幅より低くなることがあります。

平均はalpha = 1 / 指定値による指数的な電力平均です。ピーク保持は平均後のスペクトルの最大値を保持します。有効化またはClear holdで現在のスペクトルから保持を始めます。入力・FFT設定・入力CHの変更やデータ欠落で平均と保持値をリセットします。取得停止中の表示設定変更では同じサンプルを繰り返し平均しません。

## 高速描画の構成

```text
Audio device → CPAL callback → bounded SPSC ring → sample history
                                                   ↓
                                    trigger / per-pixel extrema
                                                   ↓
                                  reusable GPU instance buffer
                                                   ↓
                                    wgpu shader + egui controls
```

- **CPAL 0.18**: CoreAudio / WASAPI / ALSAなどのネイティブ入力。デバイス列挙とストリーム作成はUIとは別スレッド。
- **rtrb 0.4**: 固定容量のSPSCリング。音声データのコールバックでロック・待機・メモリ確保・ログ出力を行いません。
- **egui / eframe 0.36 + wgpu**: ネイティブUIとGPUバックエンド。macOSではMetal、他の環境では対応するGPUバックエンドを選択します。
- **専用WGSLシェーダー**: 線分をインスタンスとして送り、アンチエイリアス付きの三角形へGPU側で展開します。波形全体を1回のdraw callで描画します。
- **サンプル集約**: 少数サンプルは直接接続。高密度では物理ピクセルごとの最小値・最大値を保持し、1サンプルの細いスパイクも残します。描画・転送量は画面幅に比例します。集約と測定のCPU処理は表示サンプル数に比例します。
- **上限のあるメモリ使用**: 入力キューは約0.5秒（最大262,144フレーム）、履歴は2秒分（最大FFT長の32,768フレーム以上）です。溢れたフレーム数を表示し、連番の欠落を検出すると履歴をリセットして時間の連続性を保ちます。
- **停止時の節電**: 停止中は連続再描画を止め、波形に変更がないフレームはGPUへの波形再転送を省略します。
- **複数プロット**: WGSLパイプラインを共有し、各プロットのGPUバッファ・寸法・更新番号は独立。スペクトルも物理ピクセルごとの極値を保持し、対数軸で密集する狭いピークを残します。
- **FFT**: [RustFFT](https://docs.rs/rustfft/6.4.1/rustfft/)の計画とscratchメモリを再利用します。最新の完全な窓を最大30回/秒、かつN/4以上の新規サンプルごとに解析します。すべての連続窓を網羅するSTFTではありません。

通常はVSyncを使用します。`--low-latency`ではVSyncを外します。実際の更新頻度はディスプレイ・GPU・OS・入力バッファに依存します。下部の**Performance**メニューにある`UI fps`はUI更新頻度、`Scope prep`・`FFT`・`Spectrum prep`はそれぞれの直近のCPU処理時間で、GPU実行時間ではありません。

## 検証・計測

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --all-targets -- -D warnings
./scripts/cargo.sh test --all-targets
./scripts/cargo.sh bench --bench waveform --no-default-features
./scripts/cargo.sh bench --bench spectrum --no-default-features
./scripts/cargo.sh run --release -- --list-devices
./scripts/cargo.sh run --release -- --audio-smoke
./scripts/cargo.sh run --release -- --gpu-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke --compact
```

テストはリング履歴の折り返し、型変換、モノラル／多チャンネル処理、欠落検出用の連番、トリガー、スパイク保持を確認します。ベンチマークは48k・192k・100万サンプルを1920物理ピクセルへ集約するCPU時間を計測します。GPU描画の速度やデバイス入力の遅延を測定するものではありません。

`qa`機能で`--ui-smoke`を使うと、内部テスト信号による画面を撮影できます。`--compact`との組み合わせで小さい画面も確認できます。

`--audio-smoke`は既定入力を2秒間取り込み、実際に届いたフレーム数を確認します。`--gpu-smoke`は二つのプロットを同じ更新番号で準備してから描画し、それぞれの領域をGPUから読み戻して状態の独立を検証します。`--ui-smoke`は入力を開始せず、明示的なテスト信号でScope＋Spectrumを短時間開いて閉じます。`qa`機能を有効にすると、その表示を`dist/ui-smoke.png`へ保存します。通常起動時はオーディオ入力、`--demo`指定時は内部信号を使います。GPUやマイクを必要とする確認はCIでは実行しません。

## コードの入口

- `src/audio.rs`: CPALデバイス管理、入力コールバック、SPSC転送。
- `src/signal.rs`: 固定容量履歴、トリガー、集約、測定。
- `src/spectrum.rs`: 窓、FFT、dBFS補正、電力平均、ピーク保持、周波数軸と表示集約。
- `src/demo.rs`: 外部出力を伴わない内部デモ信号。
- `src/gpu.rs` / `src/trace.wgsl`: GPUリソースと専用描画パイプライン。
- `src/app.rs`: 共通の入力操作UIと複数プロット表示。

選定したライブラリの一次資料: [CPAL](https://docs.rs/cpal/0.18.2/cpal/)、[rtrb](https://docs.rs/rtrb/0.4.0/rtrb/)、[eframe](https://docs.rs/eframe/0.36.2/eframe/)、[egui-wgpu](https://docs.rs/egui-wgpu/0.36.2/egui_wgpu/)。

## スペクトル追加版の確認結果（2026-10-04）

同じmacOS / Intel Iris Pro Graphics 6200 / Rust 1.99環境で、12件の単体テストが成功しました。追加分は窓ごとの振幅補正、DC/Nyquist補正、線形電力平均、ピーク保持・リセット、履歴折り返し、二つのトーン、対数軸のピーク保持、デモの位相連続性・矩形波の折り返し成分を確認します。

Metalの読み戻しでScope / Spectrumそれぞれの領域に412個の所定色ピクセルを確認し、GPU状態の独立を検証しました。ネイティブUIの左右・上下配置を起動・撮影して確認しました。スクリーンショットは明示的なテスト信号であり、実際の音声入力の測定結果ではありません。

release、48 kHz、1チャンネルFFT、1,920物理ピクセル、対数軸、ピーク保持あり、200回平均のCPU処理時間（解析状態リセット・DC除去・窓・FFT・dBFS変換・線分準備を含む）:

| FFTサイズ | 1回のCPU処理時間 | GPUへ渡す線分数 |
| --- | ---: | ---: |
| 1,024 | 0.040 ms | 1,022 |
| 8,192 | 0.319 ms | 3,266 |
| 32,768 | 1.255 ms | 4,748 |

GPU実行時間、動作中UIのフレーム時間分布、入力から表示までの遅延はこのベンチマークに含みません。

## 初期版の確認結果（2026-10-04）

macOS / x86_64 / Intel Iris Pro Graphics 6200 / Rust 1.99で確認しました。

- 6件の単体テスト、`cargo fmt`、全ターゲット・全機能の`cargo clippy -D warnings`が成功。
- 内蔵マイクを48 kHz・2チャンネルで2秒間取得し、95,744フレーム、欠落0を確認。
- Metalで専用シェーダーを実行し、読み戻した画像で2色の線を確認。
- ネイティブ画面の起動・終了と、テスト波形のスクリーンショットを確認。
- ローカル用のmacOSアプリを生成し、署名の検証とInfo.plistの検査に成功。サイズは約12 MB。

release設定でのCPU集約・測定時間（1920物理ピクセル、2チャンネル、200回の平均）:

| 表示サンプル数 | 1回の処理時間 | GPUへ渡す線分数 |
| --- | ---: | ---: |
| 48,000 | 0.335 ms | 7,678 |
| 192,000 | 0.987 ms | 7,678 |
| 1,000,000 | 4.745 ms | 7,678 |

この計測はCPU処理の時間で、GPU実行時間・フレームレート・音声入力の遅延は含みません。Windows / Linux向けのCI設定は追加していますが、この環境での実機検証はmacOSのみです。

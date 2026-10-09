# Spectrumの524,288点対応と検証

更新日：2026-10-09。通常アプリに65,536／131,072／262,144／524,288点を実装した。今回の検証対象は`70766819`を基点とした未コミットの作業ツリー。対象Rustファイル・ベンチマーク・CargoファイルのSHA-256と実行バイナリはローカルQA成果物`dist/large-fft-validation/`のsource-manifestで識別する。initialは単体bench・4表示の短時間／600秒失敗、before-activityは小さいLatestの回帰維持と診断追加後、finalはmacOS activity対応後の条件を表す。その実測後に小さいFFTの観察間隔の説明表示を33 msへ整合させたが、演算・転送・観察処理は変更していない。実装状態と残る完了条件は [PLANの3e](../PLAN.md#3espectrumの524288点対応) に保持する。以下の今回の結果と、後半の2026-10-08の隔離調査を区別する。

## 現行の実装と測定条件

* Spectrum専用ワーカーへ、選択1chのf64サンプルを1,024フレーム×256ブロックの固定容量SPSCで渡す。取得ワーカーはFFT計画・演算・結果配信を待たない。通常の約2 msの入力消費でも部分ブロックをflushするため、保持時間は最大フレーム数だけで決まらない。今回の最長計画・演算時間とキュー高水位を併記する。
* 大きな履歴は選択CHのNフレームだけ。全CHのScope／XY履歴はmax(2 × Fs, 32,768)のまま。Spectrum結果は独立した3個のプール、入力・解析世代と更新番号を持つ。Scope更新だけではSpectrumをコピー・再集約しない。ピークと帯域積算も新結果または表示範囲変更に対応して更新する。
* ContinuousはN/4 hopの全完全窓で振幅／PSD・線形電力EMA・保持を更新する。Latestの新4サイズは100 msごとに新終端の完全窓を観察し、N/4制限を使わない。32k以下の周期観察は従来の33 ms以上／N/4以上の進行を維持する。EMA α = 1/4を含む従来の定義、f64数値とf32描画の分離、3窓・DC除去を維持する。
* Stopは取得済みの有限終端を固定し、UIを止めずに解析完了を待つ。Latestの最終完全窓は同じ終端なら再平均しない。停止中の次回設定変更は保持値を変えず、再開・CH／設定変更で完全窓の充填から始める。Spectrogramは1,024〜32,768点に限定する。
* 今回の環境はmacOS 14.8.9（23J631）、x86_64、Intel Core i5-4690 3.50 GHz、4コア／4論理CPU、Metal / AMD Radeon R9 M290X。rustc 1.99.0（b940084d7、2026-09-28）、Cargo 1.99.0、RustFFT 6.4.1。release、thin LTO、codegen-units = 1、f64、通常VSync。過去の隔離調査とはCPUが異なる。

## 今回の数値・転送・GPU検証

`cargo fmt --all -- --check`、全ターゲット・全機能のClippy（警告をエラー化）、全ターゲット・全機能のテスト、通常desktopとqaのreleaseビルドを実施。テストは95件成功。小さいLatestの周期観察条件も回帰確認した。Ruff check／format checkも成功。各テストは現行本体のソースを使い、コピーした旧probeではない。

| 条件 | 独立した基準・許容差 | 今回の結果 |
| --- | --- | --- |
| 全サイズ・3窓・DC除去有／無・振幅／PSD・f64／f32 | 全長複素f64 FFTの全ビンと比較。sqrt(P)の絶対差はf64 < 1e−13、f32 < 2e−7（FS peakまたはFS/√Hz） | 成功。DC、Nyquist、ビン間トーン＋別トーンを含む |
| 新4サイズを含むPSD Parseval、過渡、DC／Nyquist | 時間領域の窓付き平均二乗。独立した256点区分の積算。FS²の絶対差はf64 < 2e−13、f32 < 5e−8 | 成功 |
| 全サイズ・3窓・44.1／48／96／192 kHzの2トーン帯域 | 解析式の帯域電力（0.125、0.03125 FS²等）、絶対差 < 1e−13 FS²。PSD中心値は相対差 < 1e−13 | 成功。公称Fsによる演算であり実時計の検証ではない |
| 新4サイズ・3窓・DC除去有／無の強弱混在 | DC 1 FS＋0.5 FS peak＋1e−8 FS peak。f64の強トーン絶対差 < 1e−12、弱トーン < 5e−15 FS peak | 成功 |
| 全サイズ・3窓の既知白色雑音 | xorshiftの一様±0.2 FS、32窓。全帯域平均は既知分散の3%、6〜12 kHzの密度は8%以内 | 成功 |
| 1,024／32,768と新4サイズの連続窓・平均・保持 | 振幅／PSDで3N入力、9窓。独立に逐次解析した全f64ビン・保持・平均区間に完全一致 | 成功。結果配信回数に依存しない |
| 512kのLatest、欠落、過渡、保持 | N/4未満の新終端も観察。最終窓は再平均しない。完全窓から回復。Continuousの保持はLatestが見逃すインパルスを捕捉 | 成功 |
| 512kの合成Capture転送とStop／再開 | 44.1 kHz・1ch、48 kHz・2ch、96 kHz・2ch Latest、192 kHz・16ch/CH 16。N＋2 hop。FFTを含まないScope配信、従来の全CH履歴容量、世代・CH・有限終端、待機中の次回設定変更、Clear holdを確認 | 成功、取得／解析入力／無効窓の欠落0。供給は1,024フレームごとに取得消費を確認する合成入力で、各Fsの実時間・CPAL試験ではない |
| 意図的なSpectrumキュー飽和 | 容量1ブロックの実際のproducerを停止したconsumerへ供給。1,024フレームの末尾欠落と回復後の区間・平均を照合 | 成功。取得側を待たせない。無効窓は回復点まで重なる旧hop予定窓を数えるため、有限終端で欠落を通知した時点では将来の回復窓までの無効予定も含む |
| 広い／狭い表示・GPU読み戻し | ピクセル極値によるピーク保存・線分上限、512k f64の1,500 Hzピークを1,499〜1,501 Hzへ表示 | 成功。Metalでピーク位置の青画素を確認。Scope 412、Spectrum 346、XY 985画素。停止時の再転送除外と最大32kのSTFT画像も成功 |

## 今回のrelease単体計測

本体の`benches/spectrum.rs`を実行。5回ウォームアップ、200回、p95はソート後190番目。48 kHz・周期Hann・DC除去・EMA α = 1/4・0.5 FS peak/bin 123。静的な同じ窓を反復したCPU計測で、Continuousの実時間試験ではない。解析は入力コピー・前処理・半サイズ複素FFT・電力EMA・保持・dB変換を含む。取得・キュー・UI／GPUは含まない。FFTだけと前後処理だけの個別時間は未分離。結果コピーと描画集約は別々に計測し、p95を足して総遅延とは扱わない。

| N（f64） | 計画1回 ms | 解析平均 ms | 解析p95 ms | 解析最大 ms | コピーp95 ms | Log集約p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| 32,768 | 1.379 | 0.491 | 0.492 | 0.517 | 0.017 | 0.068 |
| 65,536 | 2.723 | 1.003 | 1.007 | 1.042 | 0.034 | 0.130 |
| 131,072 | 5.335 | 2.194 | 2.346 | 2.559 | 0.068 | 0.251 |
| 262,144 | 10.836 | 4.769 | 4.854 | 5.172 | 0.257 | 0.616 |
| 524,288 | 22.381 | 10.211 | 10.338 | 11.273 | 0.521 | 1.098 |

Logは1920物理ピクセル、20 Hz〜Nyquist、保持有、座標キャッシュ済み。512kでは3,826線分。Linearのbin 123±1 Hz集約は3桁ms表示で0.000 ms（0と断定しない）。f32の512kは解析平均8.446 ms、p95 8.531 ms、最大9.015 ms。必須のf64をf32で代用していない。

## 今回の実時間UI検証

48 kHz・2chの内部生成、750 Hz・0.125 FS peak・雑音0・CH間90度、Spectrum 512k f64／周期Hann／DC除去／EMA α = 1/4、STFT 8,192 f64を共通条件とし、表示数を各試験へ明記する。`MEASURELAB_PROFILE_DEMO_BIN_TONE=1`でこのQA入力を固定した。CPAL・外部仮想I/O・Software Loopback・物理I/Oの確認とは分ける。通常条件とUI停止・設定変更・撮影の条件も別に記録する。

### 4表示・macOS activity対応前

* 小さいFFTの従来UIライフサイクル／停止中アイドルQA（5秒＋起動待ち）も成功。32,768点の最終Continuousは17予定窓、取得／解析入力／無効窓／STFT入力／結果の欠落0。
* 40秒の大規模FFTライフサイクルQA（起動待ちを含む42.0秒）：非同期Stopの要求受付0.013 ms、次のUIでの完了観察16.967 ms（各1回、p95ではない）。保持中の設定・データ、細い表示範囲、Clear hold、再開後のCH 2／PSD／Latest、非表示でも10窓以上の解析、最終窓を確認。取得／Spectrum入力／無効窓／STFT入力／STFT結果の欠落0。FFT p95 22.3 ms（0.1 ms上側丸め）、最大22.258 ms、設定準備最大27.971 ms、入力消費1バッチ最大1.529 ms、Spectrumキュー高水位12/256。UI間隔p95 17.010 ms、最大98.033 ms、eframe処理p95 1.860 ms。状態変更・撮影を含むため通常の負荷基準値とはしない。Latestの強制最終窓込みの11更新を10 Hzの周期観察回数とは扱わない。

* 30秒＋起動待ちのContinuous/UI停止QA：充填後、実UIを8.192秒（3 hop）停止。その間393,304入力フレームと3 FFT窓が進行。有限終端1,535,037に対して8予定窓を照合し、平均後の振幅も許容差内。取得／Spectrum入力／無効窓／STFT入力の欠落0。Scope配信省略234、STFT結果の表示行欠落65を別に数えた。FFT p95 20.8 ms、最大20.791 ms、計画最大29.171 ms、入力消費1バッチ最大4.213 ms、キュー高水位13/256。意図的なUI停止を含む間隔最大8,220.467 msは通常性能値ではない。
* 20秒＋起動待ちのLatest/PSD/compact QA：111更新（強制最終窓込み）、終端1,053,856、観測した終端間隔による更新率9.971 Hz。100 ms観察の目標に対応する。PSD全帯域0.0078125 FS²との差 < 1e−12、取得／Spectrum入力／無効窓／観察漏れ／STFT入力／結果の欠落0。FFT p95 13.6 ms、最大14.866 ms、計画最大27.563 ms、入力消費最大0.470 ms、キュー高水位13/256。UIは17,690更新、間隔p95 1.380 ms、eframe処理p95 1.330 msで、この実行ではVSync設定に対してUI更新が非制限で進んだ。可視画面の60 fps基準値とは比較しない。撮影要求の画像は受信されず、compactの見た目の確認とは扱わない。

* 4表示のContinuous/600秒試験（起動待ち込み602.0秒）は失敗。取得欠落23,729,268、消費5,007,229フレーム、FFT総数8。最終時点では連続窓の再充填中で、振幅・予定窓数の終端照合に至らなかった。Spectrum転送の欠落は0、高水位14/256、FFT p95 14.9 ms／最大14.818 ms、計画最大31.696 ms、入力消費1バッチの処理最大47.232 ms。演算時間だけを原因とせず、取得消費の実行間隔とOSの実行条件を追加計測する。この時点のQAは未充填時に既知入力の判定を飛ばして終了コード0を返していたため、今回修正した。終了コードを成功根拠にしない。UIは524,903更新で非制限動作、間隔p95 1.390 ms、eframe処理p95 1.350 ms。
* この失敗試験の30〜602秒のRSSは143.37〜147.05 MiB、先頭143.68／末尾145.96 MiB。psの累積CPU時間差608.35秒／実経過572秒 = 106.35%（1論理CPUを100%とする全プロセス値）、1秒サンプルのCPU率平均106.26%。負荷・安定性の成功判定や、可視60 fpsの基準としては使わない。限界条件はSpectrum 1個の表示でも受け入れ、4表示の結果と分ける。非表示の取得・演算は継続する。

### Spectrum単独・macOS activity対応前

* macOS activity追加前のSpectrum単独試験は約30秒まで欠落0／7窓だったが、60秒の記録で消費1,479,186、取得欠落948,098、FFT総数8、デモの入力消費間隔最大20,002.049 ms／250 ms超1回となり、途中で打ち切った。外部caffeinateによるシステム／画面スリープ抑止を付けても再現した。sampleの取得ワーカースタックは制御キューの時間付きsemaphore待機で、FFT実行ではなかった。
* macOSでは入力のStart〜Stop／失敗／終了だけ、NSProcessInfoのUserInitiated＋LatencyCritical activityを保持する。取得済み有限終端を固定した後には解除する。[Appleのactivity API](https://developer.apple.com/documentation/foundation/processinfo?language=objc)が音声記録のような高優先I/Oへ提供する時間精度の要求を使う。App Nap／タイマー抑制の影響を避けるための対応であり、OS設定・取得デバイスを越えた締切保証とはしない。外部スリープ抑止だけの失敗と、この対応後の再試験を分ける。

### Spectrum単独・macOS activity対応後

4表示の通常条件とは別の限界条件。表示はSpectrum 1個、Scope／XYの共通履歴と統計・配信、STFT 8,192の演算・結果取り込みは非表示でも継続する。外部caffeinateは付けない。プロセスの入力activityが実行中に存在することと、終了後の消失をpmsetで観察した。画面の遮蔽・表示同期の実効動作は固定できておらず、次のUI更新は非制限で進んだ。可視画面の60 fps達成としては扱わない。ビルド・benchと試験を重ねていない。

* Continuous 600秒（起動待ち込み602.0秒）：取得28,894,466フレーム。予定窓数1＋floor((end−N)/(N/4)) = 217に完全一致、最終FFT終端28,835,840。取得／Spectrum入力／無効窓／STFT入力／結果の欠落0。振幅0.125 FS peakとの差 < 1e−12。FFT p95 13.9 ms、最大15.358 ms、計画最大25.197 ms、入力消費処理最大14.454 ms、デモの入力消費間隔最大124.927 ms、250 ms超0回、高水位10/256。UI 709,003更新、間隔p95 0.910 ms／最大11.353 ms、eframe処理p95 0.870 ms。ワーカーの計測CPU時間はSpectrum 3,425.801 ms、取得・統計・配信8,866.118 ms、STFT 2,905.136 ms。
* 同600秒の30〜602秒のRSSは140.30〜141.05 MiB、先頭140.30／末尾140.82 MiB。ps累積CPU時間差652.88秒／実経過572秒 = 114.14%、1秒サンプルのCPU率平均113.84%。100%は1論理CPUで、4論理CPU全体の100%ではない。これは非制限のUIと非表示の演算を含む全プロセス値。GPU時間・システム全体のCPUではない。観測区間内でRSSは上記範囲に収まり、容量固定の転送で217窓を完了した。
* Latest／PSD 20秒＋起動待ち：110更新（強制最終窓込み）、最終／取得終端1,053,818、観測した終端間隔の更新率9.883 Hz。PSD全帯域0.0078125 FS²との差 < 1e−12。取得／解析入力／無効窓／観察漏れ／STFT入力／結果の欠落0。FFT p95 13.1 ms／最大16.061 ms、計画最大28.937 ms、入力消費最大0.794 ms、消費間隔最大43.850 ms、高水位13/256。UI 22,257更新、間隔p95 1.030 ms、eframe処理p95 0.990 ms。撮影要求の画像は受信されず、単独表示の目視確認とは扱わない。
* 単独表示の40秒ライフサイクル：非同期Stop受付0.099 ms、完了観察17.095 ms（各1回）。保持中の次回設定・窓／値／履歴、750 Hz周辺の狭い範囲、Clear hold、CH 2／PSD／Latestでの再開、非表示でも10更新以上、最終窓の保持を確認。取得／解析入力／無効窓／STFT入力／結果の欠落0。FFT p95 17.6 ms、最大17.581 ms、計画最大29.896 ms、高水位12/256。最後の強制窓を含む11更新の率10.824 Hzを周期観察10 Hzの実測値とは扱わない。

### 容量上限と再実行

選択CH履歴は512k ×（f64 8 byte＋有効フラグ1 byte）= 4.5 MiB。Spectrumの各結果は262,145 ×（f64電力・f64保持・f32 dB・f32保持）≈ 6 MiB、配信3個で約18 MiB、UIで約6 MiB。Stop／Scope要求の返信はプール外へ結果と生履歴を1個複製するので、返信待機中の一時容量も別に加わる。通常UIはStopとScopeを各1個まで待機し、ワーカー側の制御キューは32個を上限とする。Analyzerの入力・窓は計8 MiB、複素FFT入力は4 MiB、twiddleは約4 MiB、Analyzerの数値／表示出力は約6 MiB、scratchはRustFFT計画が指定する有限容量。FFT計画内部の割当は未集計。入力ブロックのサンプル領域は2 MiB＋固定のメタデータ。座標キャッシュは最大262,145要素（1要素24 byte、Vecの増分確保を含む上限約12 MiB）。線分は物理幅に応じて最大約4 × pixels、1,920 pxなら最大7,680本。GPUバッファの増分確保と実行時間は別に扱う。

48 kHzの全CH履歴は1個あたり2ch ≈ 1.56 MiB、16ch ≈ 11.81 MiBで、コア＋Scope配信3個＋UIの5個は約7.78／59.05 MiB。512k設定によって全CH履歴を拡大しない。Fs／CH切り替えで再利用されるVecはセッション中の最大容量を保持し得る。RSSにはこれら以外のSTFT、画像、GPUドライバ、OS・UIの割当も含み、容量式だけをRSS実測としない。

```bash
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh bench --locked --bench spectrum --no-default-features
./scripts/cargo.sh build --release --locked --features qa
target/release/measurelab --gpu-smoke
MEASURELAB_PROFILE_SECONDS=40 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_DEMO_BIN_TONE=1 \
    MEASURELAB_PROFILE_LARGE_LIFECYCLE=1 \
    ./scripts/profile-stage2.sh large-fft-lifecycle --demo
MEASURELAB_PROFILE_SECONDS=30 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_DEMO_BIN_TONE=1 \
    MEASURELAB_PROFILE_UI_STALL=1 \
    ./scripts/profile-stage2.sh large-fft-ui-stall --demo
MEASURELAB_PROFILE_SECONDS=20 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_DEMO_BIN_TONE=1 \
    MEASURELAB_PROFILE_SPECTRUM_MODE=latest MEASURELAB_SPECTRUM_PSD=1 \
    ./scripts/profile-stage2.sh large-fft-latest-psd --demo --compact
MEASURELAB_PROFILE_SECONDS=600 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_DEMO_BIN_TONE=1 \
    MEASURELAB_PROFILE_SPECTRUM_ONLY=1 \
    ./scripts/profile-stage2.sh large-fft-spectrum-only-600 --demo
MEASURELAB_PROFILE_SECONDS=20 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_DEMO_BIN_TONE=1 \
    MEASURELAB_PROFILE_SPECTRUM_ONLY=1 MEASURELAB_PROFILE_SPECTRUM_MODE=latest \
    MEASURELAB_SPECTRUM_PSD=1 \
    ./scripts/profile-stage2.sh large-fft-spectrum-only-latest --demo
```

ローカル成果物は`dist/large-fft-validation/`の環境・ソース／バイナリ識別・テスト／Clippy／ビルド／bench／GPUログ、`dist/stage2-qa/large-fft-*.log`とRSS CSV、`dist/large-fft-validation/large-fft-ui.png`。Git管理外なので他のcheckoutには存在しない。CSVのCPU列は今回追加したpsの全プロセス値で、古い2列のRSS CSVにはない。QAは30秒ごとの取得数・窓数・デモ生成の消費間隔最大と250 ms超の間隔数も出力する。デモはこの超過区間を実入力のように欠落とし、未取得サンプルを補っていない。

## 過去の隔離調査（2026-10-08）とBIN幅

調査対象は`605e4c19f6bda1cafd78f2ca323b256ae3d43302`。以下は当時の隔離調査であり、今回の統合検証ではない。RustFFTによる実FFTで524,288点を扱える見通しを得た。隔離試験のf64解析は平均8.683 ms・p95 11.971 msであり、旧版の大きなFFTの100 ms更新を目指す計画に対しても余裕がある。調査時点では取得・ワーカー間転送・GUIを含む性能は未検証で、通常アプリは32,768点までだった。FFTWは採用せず、旧版のwisdomは参考経緯として扱う。

512kは524,288点の実入力窓を意味する。同じFsでは32,768点の1/16のBIN幅を得る。例えば48 kHzでΔf = 48,000/524,288 ≈ 0.091553 Hz、周期HannのRBW ≈ 0.137329 Hz、窓時間 ≈ 10.9227秒。44.1／96／192 kHzの値はPLANにまとめる。

BIN間隔、窓によるRBW・主ローブと漏れ、周波数の読み値の精度、入力時計の誤差を区別する。細かいBINは任意の2信号をその間隔で分離できる保証ではない。ゼロパディングで短い実入力の分解能を524,288実サンプル相当とは扱わない。開始・設定変更・欠落後は完全な窓の充填を待つ。

## 旧Python版から参考にするもの

旧アプリの環境は復元せず、Gitの内容を読むだけに限定した。以下の行番号は`archive/python-v0.9.1`／`v0.9.1`の参照先`b7a10b1a18249758a2fa847c33cb9a23fde73790`に対するもの。

| 参照先 | 確認した実装 | 今回の扱い |
| --- | --- | --- |
| `src/core/fft_manager.py` | MEDIUM_SIZESに131,072／262,144／524,288。既定ESTIMATE、明示的なMEASURE、wisdomの保存・読込、計画／aligned bufferの再利用。8,192以下は1スレッド、それ以上は最大8スレッド | FFTW固有の最適化機能は移植しない。計画・作業バッファの再利用をRust側で維持 |
| `src/gui/widgets/spectrum_analyzer.py:43`、`:130`、`:175` | 600,000点以上で別のSnapshot動作。524,288点は通常の循環バッファと最新窓の読み出し | 512kを通常のサイズ選択へ加え、巨大FFT専用の別操作を必須にしない |
| 同ファイル`:1296` | 131,072点以上は100 ms、32,768点以上は60 ms、小サイズは30 msのUIタイマー | 大きなFFTのLatest観察は100 ms更新を目標にする。Scope等の表示頻度・Continuousのhopとは分ける |
| 同ファイル`:1449`、`:1511` | ピクセル幅・表示中のビン数からRAW／最小最大包絡を選ぶ。ズーム時は生のビン、広い表示は極値集約 | Rustの既存LineBuilderを使い、ズームして細かいビンを読めることと、広い表示で細いピークを落とさないことを検証 |
| 同ファイル`:1068` | 生スペクトルのピークマーカー検出を別の間隔で更新 | 追加の全ビン走査を画面の全フレームへ結び付けない |

旧版の`update_plot`はキュー消費・FFT・描画を同じUIタイマーで進める。旧版の操作実績は参考になるが、UI停止中も取得・Continuousの平均／保持を継続する現行要件の検証には代えない。旧版を今回再実行した性能値や、すべての解析窓が連続する保証はない。

## 調査当時のコードの制約（現行状態ではない）

| 入口 | 現在の制約・負荷 | 必要な変更 |
| --- | --- | --- |
| [spectrum.rs](../../../src/spectrum.rs)のFFT_SIZES・Analyzer::new | 最大32,768の一覧とassert。Workspaceは既にN/2複素FFTで実入力を処理し、計画・scratch・twiddleを再利用 | Spectrumの一覧を拡張。全長複素FFTへ戻さず、数値定義を維持 |
| [measurement.rs](../../../src/measurement.rs)のCore::start・Core::push | 全CH履歴はmax(2 × Fs, 32,768)。通常Fsでは512k窓が入らない。FFT中は同じワーカーの入力消費・STFTへの供給が止まる | 選択CHの大きなf64履歴とFFTを別ワーカーに持たせる。キュー容量と欠落・回復を検証 |
| 同ファイルのCore::copy_snapshot | 全CH履歴とSpectrum全ビンを最大30回/秒コピー。結果プールは3個 | Spectrum結果を独立した更新番号・容量固定配信にし、同じFFT結果を毎回コピーしない |
| [app.rs](../../../src/app.rs)のaccept_snapshot | Scope側の新スナップショットごとにSpectrumもdirty。UIはバッファをswapして受信するが、同じスペクトルを再集約する | FFT結果更新・表示条件変更・幅変更のときだけ再集約・GPU転送 |
| [spectrum.rs](../../../src/spectrum.rs)のLineBuilder | ピクセルごとの極値と座標キャッシュが実装済み。集約自体は表示範囲の全ビンを走査 | 既存経路を維持し、必要なら走査範囲と表示用dB更新の頻度を改善 |
| [measurement.rs](../../../src/measurement.rs)のCore::latest | 30回/秒の観察制限に加え、終端の移動もN/4以上が必要。512k・48 kHzでは約2.73秒より速い観察にならない | Latestの100 ms観察ではN/4制限を外す。新終端・観察間隔・平均条件を結果へ対応させる |
| [stft.rs](../../../src/stft.rs)、[app.rs](../../../src/app.rs) | SpectrumとFFT_SIZESを共有。STFT結果は32,768点相当の固定MAX_BINSで128行 | サイズの検証・選択を分ける。一覧だけ拡張して結果のsliceが容量を越える経路を作らない |
| [spectrogram.rs](../../../src/spectrogram.rs) | 512行・幅4,096のtexture strideをNから計算 | 512kを自動開放しない。拡張にはメモリ・texture寸法・GPU検証が必要 |

FFT計算速度のほか、履歴の所有・転送、結果の更新番号、設定準備・Stopの非同期境界が実装対象になる。既存の[stft.rs](../../../src/stft.rs)は選択CHだけの固定長f64ブロックに世代・サンプル位置・欠落を付けており、Spectrumの転送境界を設計する参考になる。

### Rustライブラリの方針

[RustFFT 6.4.1の公式資料](https://docs.rs/rustfft/6.4.1/rustfft/)ではFftPlannerがCPUに応じてAVX／SSE／NEONを選択し、2の冪乗は高速なサイズに含まれる。524,288点の実FFTは現行方式で262,144点の複素FFTを使う。[FftPlannerの公式資料](https://docs.rs/rustfft/6.4.1/rustfft/struct.FftPlanner.html)に従い、設定準備が問題なら同じplannerやArcを再利用する容量制限付きキャッシュを評価する。

[RealFFT 3.5.0の公式資料](https://docs.rs/realfft/3.5.0/realfft/)も偶数NではN/2複素FFT＋後処理を使う。現行実装も同じ構成なので、導入だけで大幅に高速化すると推定しない。必要になった場合に前後処理・バッファ量・f64数値結果を同じ条件で比較する。

## 隔離した演算・描画集約の試験

### 条件と再実行

* macOS 14.8.9（23J631）、x86_64、Intel Core i5-5675R 3.10 GHz、4コア／4論理CPU。rustc／Cargo 1.99.0、RustFFT 6.4.1の既定機能。release、thin LTO、codegen-units = 1。1スレッドで順に計測し、並行ビルドは行っていない。
* 現行の`channel.rs`、`cursor.rs`、`signal.rs`、`spectrum.rs`をGit管理外の`dist/large-fft-investigation/probe/`へコピー。コピーしたSpectrumのFFT_SIZESだけを新4サイズまで拡張した。計測用mainは別に用意し、本体のRustファイルとCargo.toml／Cargo.lockは変更していない。
* 各項目は5回ウォームアップ後、200回を個別に測定。p95はソート後の190番目。表は1回の試験系列で、CPU固定・反復系列によるばらつき評価は未実施。設定準備はAnalyzer::newの1回の時間で、p95ではない。
* 入力は0.5 FS peak・bin 123のf64正弦波、48 kHz、周期Hann、DC除去、EMA α = 1/4。静的入力の同じ窓を反復し、実時間の連続性や平均の更新間隔は測っていない。
* 解析総時間は`update_samples`の入力コピー・DC除去・窓・実FFT・電力EMA・保持・全ビンのdB変換を含む。取得・ブロックキュー・履歴からのCH取り出し・結果コピー・UI・GPUは含まない。後述の履歴経由試験はCH取り出しを含む。
* 描画集約は1920物理ピクセル、Log 20 Hz〜24 kHz、保持あり、座標キャッシュ済み。狭帯域はLinear 990〜1010 Hz。線分生成のみで、egui・軸文字・GPU実行は含まない。

ローカルQA成果物は`dist/large-fft-investigation/results.csv`、`environment.txt`、`probe/src/main.rs`とコピーしたソース・Cargo.lock。Git管理外のため他のcheckoutには存在しない。残っている同じprobeを再実行するコマンドは以下。別リビジョンで比較するときはコピー元・拡張差分を確認し、同条件でprobeを作り直す。

```bash
./scripts/cargo.sh build --release --offline \
    --manifest-path dist/large-fft-investigation/probe/Cargo.toml
dist/large-fft-investigation/probe/target/release/measurelab-large-fft-probe \
    > dist/large-fft-investigation/results.csv
```

### f64の実測値

単位はms。設定準備を除き各項目は別々に測定し、p95同士を足して総遅延とは扱わない。

| N | 設定準備1回 | 解析平均 | 解析p95 | 解析最大 | 結果コピーp95 | Log集約p95 |
| --- | --- | --- | --- | --- | --- | --- |
| 32,768 | 2.333 | 0.395 | 0.447 | 0.580 | 0.019 | 0.100 |
| 65,536 | 2.694 | 0.834 | 1.004 | 1.299 | 0.040 | 0.153 |
| 131,072 | 7.073 | 1.790 | 2.139 | 3.039 | 0.139 | 0.367 |
| 262,144 | 10.766 | 3.988 | 5.065 | 8.141 | 0.431 | 0.900 |
| 524,288 | 21.333 | 8.683 | 11.971 | 33.626 | 0.812 | 1.439 |

524,288点のf32は解析平均6.917 ms・p95 7.728 ms・最大20.215 ms、結果コピーp95 0.629 ms、Log集約p95 1.092 ms。f64の性能を成立させることを優先し、f32を必須にしない。512kの狭帯域集約は両精度ともp95約0.001 ms。Log集約の線分はf64で3,826本、f32で4,670本で、丸めによって弱いビンの極値が異なるため同じ本数とは限らない。

48 kHz・N/4のhopは2,730.7 ms、100 ms観察の予定予算は100 ms。単体試験のp95 11.971 msはどちらよりも短く、後者の25 ms目標も下回る。これは統合動作の締切保証ではない。観察を10回/秒行う場合の解析平均からの見積りは1コアの約8.7%だが、転送・取得・他の解析・GUI・GPUを含む総CPU負荷は未計測である。

### 全CH履歴を一律に広げる場合の負荷

N = 524,288のHistoryを作り、同じ容量の宛先へのclone_fromと、選択CHの`Analyzer::update_window`を別に測定した。f64・Hann・同じ入力、各200回。

| 入力CH数 | Historyのデータ＋有効フラグ | 履歴コピーp95 | CH取り出し込みの解析p95 |
| --- | --- | --- | --- |
| 2 | 8.5 MiB | 0.930 ms | 12.858 ms |
| 16 | 64.5 MiB | 18.031 ms | 19.269 ms |

現在の構造のまま16ch履歴をNへ広げると、コア1個＋表示プール3個＋UI1個の履歴だけで約322.5 MiBになる。30回/秒の全履歴コピーはデータ量で約1.89 GiB/秒。有効フラグを1バイト、f64を8バイトとして計算した容量・転送量で、RSSの実測値ではない。

Spectrumの1結果は262,145ビン ×（f64電力・f64保持・f32 dB・f32保持）で約6 MiB。計画では大きな履歴を選択CHに限定し、結果コピーを新しい解析結果の配信だけへ結び付ける。単純にFFT_SIZESと共通履歴の上限を上げる変更は避ける。Spectrogramへ同じ上限を適用すると128行の結果プールだけで約128 MiB、512行の画像も約512 MiB以上となるため、今回の対象から分ける。

### 少数の数値照合

全5サイズ（32,768と追加4サイズ）・f64／f32で、ビン中心0.5 FS peakの振幅と、ビン間トーン＋別トーン＋DC＋NyquistのPSD全帯域積算を照合した。振幅の基準は解析式、PSDの基準は独立して求めた時間領域のHann窓付き平均二乗。PSDはDC除去なし・EMA α = 1。

| 対象 | 試験の絶対許容差 | 観測した最大絶対誤差 |
| --- | --- | --- |
| f64振幅 | 1e−12 FS peak | 5.551e−16 FS peak |
| f32振幅 | 2e−7 FS peak | 2.980e−8 FS peak |
| f64 PSD全帯域 | 1e−12 FS² | 3.025e−15 FS² |
| f32 PSD全帯域 | 5e−8 FS² | 1.502e−8 FS² |

隔離調査の少数信号は試験の許容差内だった。当時は新サイズの全ビン参照比較、3窓、DC除去の全条件、強弱混在、雑音、欠落・平均・保持のライフサイクルは未検証だった。今回の拡張検証の結果は前半の「今回の数値・転送・GPU検証」に保持する。

## 残る確認と完了条件

* 今回列挙された入力はBuilt-in Microphoneのみで、BlackHoleはない。512kの外部仮想I/O・物理入力、96 kHz実時間、16ch/CH 16の実機確認は未実施。QAのBlackHole限定既知出力を追加したが、当該経路はこの環境で実行していない。
* activity対応前の4表示600秒試験には取得欠落があり、成功とはしない。対応後はSpectrum単独表示の600秒限界条件に成功。対応後の4表示600秒は未実施。過去のプロトタイプ600秒・隔離probeを今回の成功として使わない。
* FFTだけと前後処理だけの時間は未分離。窓終端→解析完了→表示の時刻追跡、GPU実行時間、Stop／設定受付の反復p95、FFTPLAN内部の全割当とGPUメモリの厳密な上限は未計測。UIとワーカーのCPU時間はそれぞれ記録し、総CPUと置き換えない。
* Windows／Linux、Apple Silicon、実入力時計の精度、物理校正は未確認。Software Loopbackは段階4の未実装機能のまま。
* VSyncの16.7 ms/frameは目安であり、p95のわずかな超過を達成と扱わない。測定した範囲で判定し、未確認層を残したまま3eの全条件完了とはしない。

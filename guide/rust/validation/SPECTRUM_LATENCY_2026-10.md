# Spectrumの窓終端とCPU遅延の検証

更新日：2026-10-12。段階4cで必要な同一結果の時刻追跡を対象にする。対象は`1bda9eeb`を基点とした未コミットの作業ツリーで、RustソースとQAバイナリのSHA-256はローカル成果物`dist/spectrum-latency-qa/`へ保持する。現行の完了条件は [PLAN](../PLAN.md)、操作は [README](../README.md#検証計測) に保持する。

## 計測する境界

| 時刻 | 定義 |
| --- | --- |
| 入力利用可能 | 最終サンプルを含む実入力コールバックのPCM変換前のホスト時刻。Software Loopback／内部デモは生成バッチの開始時刻 |
| 解析完了 | その整数窓のFFT・電力平均・保持・数値／表示結果の演算を終えた時刻 |
| UI描画提出 | その結果のSpectrum描画をeguiへ初めて提出したCPU時刻 |

すべて同じ単調時計を使う。入力世代・解析世代・整数窓終端で結果を識別し、窓終端のサンプルに付いた時刻を転送する。Continuousの窓が転送ブロックの途中で終わる場合も、ブロック末尾の別コールバックの時刻へ置き換えない。欠落・非有限・未充填・時刻情報なしに正常な遅延値を作らない。

3つの遅延分布は同じ提出結果群から作り、全区間も時刻差を直接計測する。入力利用可能時刻が2秒のウォームアップ区間に入る結果は、後で描画されても除外する。同じ入力／解析世代と窓終端の再描画は重複計数せず、停止中の保持画像と不可視領域は集計しない。非表示中に解析した結果を再表示で初めて提出した場合は、その待ち時間を含める。未提出の解析窓すべてを母集団とする分布ではない。

p95は既存の容量固定ヒストグラムで0.01 msの上側へ丸める。200 ms以上のバケットにp95が入る場合は、その分布の実測最大値を上限として出す。最大値は実測値を保持する。p95の差や合計、UIフレーム間隔やFFT単体時間で全区間の遅延を代用しない。

## 内部の回帰条件

* 1,024／524,288点、Continuous／Live／Latestで窓終端とその入力時刻を照合する。終端後に別時刻の37サンプルを渡し、Continuousは完全窓の終端時刻を保持し、Live／Latestの有限Stopは最後の取得済み終端へ対応することを確認する。
* Clear holdの再配信は元の解析完了時刻を保持し、欠落は時刻と結果を無効化する。未充填・時刻なし・非有限窓には遅延情報を配信しない。
* 共通コールバック→入力キュー→測定→Spectrum→有限Stopの経路で、可変長入力と1／2／16ch・44.1／48／96／192 kHzの切り替えを照合する。窓終端を含むコールバックの前後で読み取った時刻の間に入力利用可能時刻があることを確認する。
* 解析20 ms／UI 1 msと解析1 ms／UI 20 msが別の窓に現れる100結果を使い、各区間のp95は20 ms、全区間のp95は21 msになることを確認する。40 msというp95の単純加算を検証値にしない。
* 同一結果の再描画、ウォームアップ結果、逆順の時刻を除外し、解析設定変更・入力再開始で同じサンプル終端が再利用されても別の結果として集計する。

上記の追加4テストと共通コールバックの既存回帰は通過した。GUIなし145テスト、通常ビルド149テスト＋起動2テスト、全機能・全ターゲット157テスト＋起動3テスト、全機能docテストが成功した。全ターゲットのbenchは各条件1回の動作確認であり、その出力時間を性能値にしない。全ターゲット・全機能のClippyも警告なしで通過した。

## releaseの短時間UI確認

macOS 14.8.9（23J631）、x86_64、Intel Core i5-4690 3.50 GHz、Rust／Cargo 1.99.0。thin LTO・codegen-units 1のrelease・`qa`ビルド、VSync有効、f64・周期Hann・DC除去・電力EMA α=1/4、Spectrum 524,288点・Spectrogram 8,192点、4表示で実行した。各条件は1回で、指定30秒に起動待ち2秒を加えた区間へ意図的なUI停止を含む。実時間試験中にビルド・別の音声試験・撮影は並行実行していない。通常版とQA版のreleaseビルドは成功した。

| 条件 | UI停止と解析継続 | 有限Stop／数値の照合 | 遅延の提出結果数 |
| --- | --- | --- | --- |
| 内部デモ・2ch・48 kHz・CH 1・Latest／PSD・狭幅1040×780要求 | 8.192秒、393,329フレーム・81窓が継続 | 1,533,689フレーム・209窓、最終FFT終端は取得終端と一致。750 Hz・0.125 FS peakのPSD全帯域0.0078125 FS²を照合 | 129 |
| BlackHole 16ch・96 kHz・CH 16・Continuous／振幅・通常幅1440×860要求・仮想出力なし | 4.096秒、393,216フレーム・3窓が継続 | 3,029,504フレーム、予定20窓と一致。最終完全窓終端3,014,656。JSON保存とスナップショットの全値・条件一致を照合 | 18 |

BlackHole入力のみの保存結果は実際に取得した無信号で、262,145ビンの振幅・保持は全て0、入力失敗false、取得・Scope・Spectrumの欠落0だった。既知トーンの外部振幅精度をこの無信号で確認済みにしない。内部デモも取得／Spectrum入力／欠落窓0、デモの中断0。STFT入力欠落はいずれも0で、UI停止中の結果プール飽和による表示行欠落は内部デモ65行、BlackHole66行と別に記録した。

| 条件 | 入力利用可能→解析完了 p95／最大 ms | 解析完了→UI描画提出 p95／最大 ms | 全区間 p95／最大 ms |
| --- | --- | --- | --- |
| 内部デモ・Latest／PSD | 19.390／22.985 | 19.860／7,938.580 | 42.000／7,953.414 |
| BlackHole入力のみ・Continuous | 21.580／21.574 | 581.184／581.184 | 596.424／596.424 |

BlackHoleの解析後／全区間のp95は200 ms以上のバケットに入り、実測最大値を上限として報告した値。大きな最大遅延には意図的なUI停止の影響を含む。同じ結果群から3つの分布が出ること、入力／Spectrum欠落0と整数終端、逆転しない時刻差をログでも照合した。UIフレーム間隔p95は内部デモ18.020 ms、BlackHole18.350 msで、16.7 msの目安は未達。フレームCPU p95は3.350／2.910 ms、FFT p95は17.100／18.300 msだった。UI停止を含む少数の一系列を通常条件の性能保証や600秒の安定性へ置き換えない。

### 既知仮想出力を伴う失敗

同じBlackHole 16ch・96 kHz・CH 16・512k Continuous・4表示・30秒に`MEASURELAB_PROFILE_KNOWN_OUTPUT=1`を加えた試験は、出力コールバックでunderrun／overrun通知があり終了コード101で失敗した。4.096秒のUI停止中も393,574フレーム・3窓が継続し、取得／Spectrum入力欠落0・予定20窓を記録したが、既知信号の精度検証を通過したとは扱わない。既存の出力失敗判定で終了したため遅延統計は未出力。通知ログには時刻がなく、起動待ち中の通知か測定中の出力失敗かは確定できない。入力のみの成功でこの失敗を消さず、4cの外部既知出力・起動境界の未解決事項として残す。

### 再実行と成果物

```bash
./scripts/cargo.sh build --release --locked --features qa
mkdir -p dist/spectrum-latency-qa
MEASURELAB_PROFILE_SECONDS=30 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_SPECTRUM_MODE=latest \
    MEASURELAB_PROFILE_DEMO_BIN_TONE=1 MEASURELAB_PROFILE_UI_STALL=1 \
    MEASURELAB_SPECTRUM_PSD=1 \
    ./scripts/profile-stage2.sh latency-demo-latest --demo --compact
MEASURELAB_PROFILE_SECONDS=30 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 MEASURELAB_PROFILE_FFT_SIZE=524288 \
    MEASURELAB_PROFILE_STFT_SIZE=8192 MEASURELAB_PROFILE_SPECTRUM_MODE=continuous \
    MEASURELAB_PROFILE_UI_STALL=1 \
    MEASURELAB_PROFILE_EXPORT=dist/spectrum-latency-qa/blackhole16-input-only.json \
    ./scripts/profile-stage2.sh latency-blackhole16-input-only
```

BlackHoleのFsは試験時のDevice default（96 kHz）を使用した。別環境の既定Fsを96 kHzと仮定しない。失敗した条件の再実行は入力のみのコマンドへ`MEASURELAB_PROFILE_KNOWN_OUTPUT=1`を加える。仮想出力はBlackHoleだけに限定する。

ソース識別・QAバイナリ・環境・テスト／ビルドログ・入力のみのJSONは`dist/spectrum-latency-qa/`、3条件の実時間ログと1秒ごとのRSSは`dist/stage2-qa/latency-20261012-*.log`と`*-rss.csv`に保持する。Git管理外であり、別checkoutに存在するとは限らない。

## 計測負荷と残る範囲

時刻保持は`qa`だけに含み、通常ビルドのサンプル型・転送容量・測定演算へ追加しない。コールバックでバッチごとに時計を1回読み、既存の容量固定フレームへコピーする。動的確保・ロック・待機・ファイルI/Oは追加しない。

追加のSpectrum入力キューは `256 × 1,024 × size_of::<Option<Instant>>()` byte、実入力キューは `clamp(Fs/2, 1,024, 262,144) × size_of::<Option<Instant>>()` byte。16 byteの環境ではそれぞれ4 MiB、48 kHz入力で375 KiBとなる。処理中・保留中のブロックにも同じ時刻配列がある。3つの追加ヒストグラムは `3 × 20,001 × 8` byte（約469 KiB）で、実行時間に比例して増えない。CPU時間・RSSを過去のQAへ比較する場合は、この違いを条件へ含める。

ADCサンプル時刻、実Fs校正、物理経路の絶対遅延、GPU実行時間、実表示／scanoutは未計測。Scope／Spectrogram／XY／Lock-inの同一結果遅延、操作要求の反復p95、600秒の安定性はこの追加計測だけで確認済みにしない。外部I/Oの可変長コールバックは、内部の可変長回帰とは別に未確認として残す。

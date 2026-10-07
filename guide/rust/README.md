# MeasureLab — Rust Audio Measurement Lab

CPALで実際のオーディオ入力を取り込み、egui / eframeと`wgpu`で波形・FFTスペクトル・スペクトログラム・XY / Lissajousを同時に描画するRustプロトタイプです。この文書は現在使える操作と構成を説明します。目的・設計原則は [現在の方針](../CURRENT_DIRECTION.md)、実装状態・制限と次の完了条件は [PLAN.md](PLAN.md) を参照してください。

## 起動

Rust 1.95以上と各OSのビルドツールが必要です。開発・検証にはRust 1.99を使用しています。

### デバッグ時の簡単な起動

リポジトリのルートにある **Debug-MeasureLab.command** をmacOSのFinderでダブルクリックすると、デバッグビルドを更新して内部デモ信号で起動します。ターミナルからは以下を使います。

```sh
./scripts/debug.sh
./scripts/debug.sh --audio
./scripts/debug.sh --compact
./scripts/debug.sh --release
```

引数なしではマイク不要のデモが動きます。`--audio`では実入力を選ぶ画面で起動し、デバイスを選んで **Start input** を押します。通常はデバッグシンボルを残すdevビルドを使い、panic時のバックトレースを有効にします。`RUST_BACKTRACE`を指定済みならその値を使います。CPU処理時間などの性能確認には`--release`を使います。

初回は依存関係のビルドに時間がかかり、以後は変更した部分を再ビルドします。スクリプトは作業ディレクトリに依存せず、`scripts/cargo.sh`経由でPATH上または`.tools/`のRust環境を使います。アプリを閉じるまでターミナルにビルド結果と実行時の出力が残ります。Finderからの起動に失敗した場合はEnterを押すまでエラーを確認できます。

画面確認は次の1コマンドで実行できます。`--ui-smoke`の指定時は`qa`機能を自動的に有効にし、撮影後に終了します。画像は`dist/ui-smoke.png`へ保存されます。

```sh
./scripts/debug.sh --ui-smoke
./scripts/debug.sh --ui-smoke --compact
./scripts/debug.sh --gpu-smoke
./scripts/debug.sh --help
```

`--compact`などのアプリ引数も渡せます。`--`以降はすべてアプリへ渡すため、アプリ自体のヘルプは`./scripts/debug.sh -- --help`で確認できます。

### Cargoからの起動

```sh
cargo run --release
```

この作業環境ではプロジェクト専用のRust環境を`.tools/`に用意しています。通常の`cargo`がPATHにない場合も、次のコマンドで起動できます。

```sh
./scripts/cargo.sh run --release
```

入力デバイスを選択して **Start input** を押してください。停止すると最後の波形が保持されます。再開時は新しい入力で履歴を作り直します。音声ファイルへの保存やオーディオ出力は行いません。

通常の起動はユーザー単位のファイルロックで重複を防ぎ、2つ目は既に起動中と表示して終了します。意図的に複数起動する場合は`--new-instance`を追加してください。音声を取得するQAコマンドも同じロックを使い、デバイス列挙とGPU読み戻しは対象外です。起動制御は測定コアから分離しています。ロックファイルは残りますが、[OSのファイルロック](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock)はプロセス終了時に解放されるため、異常終了後にファイルを手で削除する必要はありません。旧ビルドにはこの制御がないため、旧版との重複は防げません。

マイクを使わず試すには、内部信号で起動します。起動後も左側の **Demo signal / Audio input** で入力を切り替えられます。

```sh
./scripts/cargo.sh run --release -- --demo
```

`--compact`を追加すると、上下にプロットを配置する小さなウィンドウで起動します。

デモでは周波数、振幅、ノイズを変更し、正弦波／高調波付き正弦波／帯域制限した矩形波を比較できます。CH 2の位相と振幅比も変更できます。**0° / 90° / 180°** ボタンはノイズなし・同振幅の正弦波を設定し、XYの同相・円・逆相を確認できます。CH 2 gainを下げると楕円になります。デモ信号は内部だけで使い、スピーカーには出力しません。

開始／停止は上部に固定しています。左の **Settings** は **Input source / Oscilloscope / Spectrum analyzer / Spectrogram / XY / Lissajous / Workspace & help** のアコーディオンで、一つの項目を開いて設定します。閉じた項目にも現在値を表示します。各グラフの **Settings** を押すと、その設定を開いて該当位置へ移動します。

グラフ上部の **Settings** で左パネルを非表示にでき、境界をドラッグすると幅を変更できます。**Collapse all** ですべての項目を閉じられます。**Workspace & help** では複数画面の配置を **Automatic / Side by side / Stacked** から選択し、ショートカットと測定単位を確認できます。4画面の場合、広い画面ではScopeとSpectrumを上段、SpectrogramとXYを下段の2列に配置します。狭い画面では上下4行に並べ、既定の`--compact`ウィンドウでは全体がスクロールなしで収まります。見出し・内側の余白・軸まわりをコンパクトにし、低いプロットでは軸ラベルを間引きます。最低高さで収まらない場合はプロット領域をスクロールできます。幅が不足する場合は左右指定でも上下に配置します。開閉や配置指定は現在のセッション内で保持します。

macOSではマイクへのアクセスを許可する必要があります。許可がない場合は「システム設定 → プライバシーとセキュリティ → マイク」で、起動に使うアプリ／ターミナルを確認してください。独立したアプリとして起動するには以下を使います。

```sh
./scripts/bundle-macos.sh
open dist/MeasureLab.app
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
| Cursor A / B / Clear | カーソルの選択／時間・周波数・XY自由配置カーソルの解除 |
| Scope上でクリック／ドラッグ | 時間カーソルのX位置を固定。各更新の波形から振幅・トリガー基準の時刻・Δtを表示 |
| Spectrum上でクリック／ドラッグ | 共通の周波数を固定。最寄りビンの振幅／PSD・対象CH・最新窓と平均の寄与区間を表示 |
| Spectrogram上でクリック／ドラッグ | 縦位置と共通周波数を固定。更新ごとにその位置の行の解析窓・ビン振幅を表示 |
| XY Free / Trace Snap | 自由配置（既定）と実サンプルへのスナップを切り替え |
| XY X Source / Y Source | X/Yへ入力CHを独立に割り当てる。Scopeの割当とは独立 |
| XY上でクリック／ドラッグ | FreeはX・Y振幅を固定しΔX・ΔYを表示。Trace Snapは最寄りの実サンプル組を選び、トリガーからの時間差を保持 |
| Horizontal / ホイール | 時間軸の変更（0.05〜100 ms/div） |
| Vertical / Shift＋ホイール | 振幅の変更（0.001〜0.5 FS/div） |
| Fit amplitude | 現在の表示振幅に合わせる |
| Scope Trace 1 / Trace 2 | 各トレースへの入力CH割当と表示切り替え。取得した1〜16chから選択 |
| Trigger | フリーラン／立ち上がり／立ち下がり、ソースと閾値の設定 |
| ダブルクリック | 時間軸と振幅を初期値へ戻す |
| Scope / Spectrum / Spectrogram / XY | 各測定器の表示切り替え。少なくとも一つを表示。広い画面では左右と上下、狭い画面では上下に配置 |
| 各グラフのSettings | 対象の設定を左パネルで開く |
| グラフ上部のSettings / Collapse all | 左パネルの表示切り替え／設定項目をすべて閉じる |
| Workspace & help | 配置の指定、ショートカット、測定単位 |
| Spectrum Source / points / Window | FFTの入力CH（取得した全chから選択）、サイズ（1,024〜32,768点）、窓関数 |
| Spectrum / Spectrogram FFT PRECISION | 各測定器のFFT精度。既定は64-bit、32-bit (fast FFT)を明示的に選択可能 |
| Continuous / Latest window | N/4 hopの連続解析（既定）／最新窓を最大30回/秒で観察。非表示でも平均・保持は継続 |
| Bin amplitude / Power spectral density | 振幅dBFS／PSD（FS²/Hz）の測定モード |
| EMA α / Remove DC | 線形値の指数電力平均、FFT前の平均値除去 |
| PSD Power in band / From / To | 指定した両端を含むビン中心のPSD積算。To = 0はNyquist。FS²とRMS FSを表示 |
| Log Hz / Linear Hz / Span | 周波数軸と表示する上限周波数 |
| Display floor / Peak hold / Clear hold | モードに応じたdB表示下限、平均後の最大値の保持、保持値のクリア |
| スペクトル上にマウスを置く | 最寄りFFTビンの実周波数と振幅／PSDをf64で読み出す |
| Spectrogram Source / FFT length / Window | Spectrumとは独立した対象CH・窓長・窓関数・DC除去 |
| Spectrogram Time span / From / To | 時間範囲（0.5〜20秒）と周波数範囲。To = 0はNyquist |
| Spectrogram Floor / Ceiling | 色のdBFS範囲。表示変更ではFFT・履歴をリセットしない |
| スペクトログラム上にマウスを置く | その行の最寄りビンの振幅・周波数と解析窓のサンプル番号 |
| XY Observation window | XYの観察時間幅（0.5〜200 ms、既定50 ms）。Freeは最新区間、Trace Snapはトリガー基準の区間を表示 |
| XY X amplitude / Y amplitude | 独立した両軸の振幅範囲（0.001〜0.5 FS/div） |
| XY Reset XY scales / ダブルクリック | XYの観察窓と両軸を初期値へ戻す |
| XY上にマウスを置く | プロット座標のX・Y振幅（実サンプルのカーソルではない） |

画面は横10分割・縦8分割です。トリガーは横20%位置で、交差が見つからない場合は最新の波形を表示するAuto動作です。コアは1〜16chを保持し、Scopeの2本のトレース、Spectrum、Spectrogram、トリガーは取得した全chからソースを選択できます。Scopeの既定割当はTrace 1 = CH 1、Trace 2 = CH 2で、同じCHを両トレースへ割り当てることもできます。16chを超える入力は切り捨てずエラーを表示します。

RMS・Peak・P-PはScopeの整数サンプル区間内に取得した生のf64サンプルから計算します。欠落は観測数へ含めず、部分区間であることを表示します。統計値の説明には対象区間と取得サンプル数を表示し、描画倍率・幅・トレースの非表示化では同じ区間の値を変えません。時間幅やトリガー条件を変えると測定区間も変わります。カーソルは割当先CHの実サンプルを読み、描画時の極値集約やトリガー補間から振幅を逆算しません。

入力CH数が減ったときもScope・XY・トリガーの割当IDを保持し、存在しないCHを別CHへ置き換えません。モノラルではScopeの既定Trace 2を利用不可とし、CH 1へ割り当てると表示できます。停止中のScope／XYのCH変更は次回Startに適用し、保持中のトレース・統計・カーソルは取得時のCHを表示します。

トリガーの位置とレベルはオレンジの「T」で示し、レベルの三角マーカーは波形領域の右外側に表示します。

振幅はCPALから取得したデジタル音声のフルスケール（FS）です。電圧への換算、外部ADCの制御、音声デバイス以外の入力は未実装です。サンプルレートはデバイス既定の設定を使用します。

Spectrumの既定モード **Bin amplitude** は片側ビン振幅のdBFSです。窓のcoherent gainを補正し、ビン中心の1 FS peak正弦波を0 dBFSとします。DCとNyquistのビンは2倍しません。振幅ビンを積算して雑音電力とは扱いません。**Δf** はFs/N、**RBW** は窓の等価雑音帯域です。48 kHz・8,192点・HannではΔf ≈ 5.86 Hz、RBW ≈ 8.79 Hz、窓時間 ≈ 170.7 ms。ピークは最大ビンの値なので、1 kHzの信号が1002.0 Hzのビンに表示される場合があります。

ビンの間にある信号は複数のビンに分散するため、ピークの読み値が実振幅より低くなることがあります。

**Power spectral density** は片側PSDをFS²/Hzで測定し、表示は10 log10(PSD / 1 FS²/Hz)の **dB re FS²/Hz** です。周期窓w、正規化前のFFTをXとすると、PSDは`c × |X|² / (Fs × Σw²)`です。cはDC／Nyquistで1、その他で2です。Remove DCは窓を掛ける前に各窓の算術平均を引きます。振幅からPSDへ切り替えると平均・保持をリセットします。Spectrogramの振幅表示は変更しません。

PSDの **Power in band** は、From〜Toの両端を含む中心周波数のビンを選び、`ΣPSD[k] × Δf`をf64で計算します。To = 0は取得時のNyquistです。実際に含めた最初／最後のビン周波数、電力FS²、平方根のRMS FSを表示します。電力とRMSは微小値も読める指数表記を使います。DC／Nyquistも全Δfの重みで含めます。半端なビンの補間や台形積分は使いません。範囲が不正、範囲内にビンがない、完全なPSD窓がない場合は利用不可とし、別範囲の値を代用しません。帯域指定と表示Spanは独立し、帯域を変えても平均はリセットしません。

単一窓の全帯域積算はParsevalにより`Σw²(x−μ)² / Σw²`に一致します（DC除去なしはμ = 0）。Rectangularでは生サンプルの平均二乗、他の窓では窓付きの平均二乗です。定常正弦波・雑音の電力評価と短い過渡の窓位置依存を区別し、Scopeの観察区間のRMSと常に同一とは扱いません。ビン間正弦波では漏れを含む十分な帯域を選んで評価します。校正された電圧・dBmは未実装です。

平均は **EMA α = 1/指定値** による指数的な線形電力平均です。最初の完全窓で初期化し、次の窓から`P ← P + α(Pnew − P)`を適用します。α = 1では最新窓だけを使います。処理窓数と最初〜最新の寄与区間を結果に保持しますが、均等な積算回数や区間全体の一様なRMSを意味しません。ContinuousはN/4 hop、Latestは最大30回/秒の最新窓だけを使い、過渡の捕捉を保証しません。カーソルの説明で最新窓・寄与区間・CH・設定・入力世代・欠落を確認できます。

ピーク保持は平均後の各ビンの最大値を保持します。有効化またはClear holdで現在のスペクトルから保持を始めます。入力・FFT設定・測定モード・入力CHの変更やデータ欠落で平均と保持をリセットします。取得停止中の解析設定変更は次回開始に適用し、保持値のモード・単位・設定を変えません。停止中の表示・帯域変更では同じサンプルを繰り返し平均しません。

数値電力・保持値・帯域積算・カーソル／ピークはf64で保持・読み出し、描画用のf32 dB配列から逆算しません。描画には−180 dBの下限がありますが、数値は下限で切り詰めません。電力0は数値上−∞ dBです。32-bit FFTは入力のDC除去後にf32へ変換し、複素結果の二乗と平均はf64で行います。f32 FFT自体の丸めや混在する強弱信号の制限は残り、微小信号の既定は64-bitです。定義・許容差と確認範囲は [Spectrumの検証](validation/SPECTRUM_2026-10.md) を参照してください。

スペクトログラムは専用ワーカーの連続STFTを表示し、新しい行が上に来ます。縦軸は最新窓の終端からの相対秒、見出しのEndは入力開始からの窓終端の秒です。各行の位置はサンプル番号とFsから計算し、1行はhop = N/4の区間に対応します。各窓のビン振幅を表示し、電力平均とピーク保持は使いません。欠落によって解析できなかった区間はオレンジの縞、まだ取得・保持していない過去は空白です。

履歴は512行で固定です。欠落がないときの保持時間は512 × hop / Fsです。48 kHz・8,192点では約21.85秒、1,024点では約2.73秒です。表示範囲を広げても履歴容量は増えません。非表示でもSTFTの履歴を更新し、再表示時に保持範囲を描画します。停止後は遅着結果を除外して画像を保持します。時間・周波数・色範囲は停止中も変更でき、解析CH・窓長などの変更は次の入力開始時に適用します。

XY / Lissajousは共通履歴の同じフレームから、X/Yへ割り当てたCHを時間順に接続します。既定はX = CH 1、Y = CH 2で、全入力CHから独立に選択できます。独立した観察窓と振幅範囲を使い、ScopeのCH割当や表示切り替えに影響されません。Freeは最新区間を表示し、Trace SnapはScopeと共通のトリガーソース・エッジ・閾値で区間を選びます。正方形の8 × 8分割プロットで両軸を同じスケールにすると、同振幅・90度位相差の正弦波が円になります。同相は右上がり、逆相は右下がりの直線です。モノラルまたは割当先CHが存在しない場合は無効にして理由を表示します。

XYの残像保持は未実装です。保持範囲内の実サンプル組を使い、欠落の前後を接続しません。描画量は最大32,768フレーム分／32,767線分に制限し、超える場合は間引かず最新の最大点数分を表示します。欠落位置も時間幅に含みます。XY下部の時間幅・サンプル区間（終端は含まない）と`point limit`で実際の範囲を確認できます。停止中も観察窓・振幅範囲を変更でき、設定や入力に変更がなければXYの線分生成・GPU線分転送を省略します。

Scopeで置いた時間カーソルA/Bは、プロット内のX位置を保持します。入力の更新・循環履歴の折り返し・時間幅の変更・画面サイズの変更でも同じ横位置に残り、各スイープの最寄り実サンプルから振幅・トリガー基準の時刻・Δtを読み直します。時間幅を変更すると時刻とΔtも変わります。Scopeを非表示にしても現在のスイープに対応するサンプルを他の測定器と共有します。取得不足でスイープがない間はカーソル線を残して待機を表示し、カーソル位置が欠落しているときは生サンプルが利用できないことを表示します。古いサンプルは代用しません。

Spectrogramで置いた時間カーソルは、プロット内の縦位置を保持します。新しい行が流れても線は移動せず、その位置の相対時刻に対応する表示上のhop区間を読み直し、解析窓全体のサンプル番号（終端は含まない）を表示します。表示時間幅を変えると縦位置を保ったまま相対時刻が変わります。欠落・未取得・保持範囲外でも線を残し、利用可能な行がない理由を表示します。欠落区間には隣のFFT窓の値を代用しません。

XYの**Free**ではクリックした位置のX・Y振幅を保持し、軌跡の更新に追従しません。A/BのX・Y値、B−AのΔX・ΔYを表示します。振幅スケールを変えると同じFS値に対応する画面位置へ移動し、範囲外の点はその旨を表示します。自由配置の点は時間サンプルを選びません。

**Trace Snap**では最も近い実サンプル組を選び、XYスイープのトリガー位置（観察窓の20%）からの整数サンプル差を保持します。重なる点は最新サンプルを選びます。各更新で同じトリガー基準の時間差にある割当先X/YのCHを読み直すため、周期信号をトリガーできている間は位置が安定します。実際の交差をオレンジの`T`で示し、`Triggered`を表示します。交差が見つからない場合は最新区間を使う`Auto (no crossing)`、フリーランの場合は`Free run (moving reference)`となり、マーカーが動く場合があります。Stopで取得を止めるとその区間と読み値を保持します。観察窓を短くして選択時刻が範囲外になった場合は実サンプルを代用しません。

FreeとTrace Snapは各グラフの見出しとXY Settingsで切り替えられます。自由配置の点と共通時間カーソルは別に保持し、切り替えて戻すとそれぞれの選択を再利用します。Clear、入力再開、ソース変更では両方を解除します。ScopeとTrace Snapの実振幅は同じ共通履歴から読みます。XYのトリガー区間は独自の観察時間幅で選ぶため、Scopeの区間と同じ交差になるとは限りません。Scope・Spectrogram・Trace Snapは現在解決した整数サンプルを他の測定器と共有し、範囲外では理由を表示します。STFTの履歴だけが残って生サンプルがない場合は、Scope／Trace Snapの値を読み出せません。

周波数カーソルはSpectrumとSpectrogramで共有します。各測定器が自身のFFTサイズ・Fsから最寄りビンを選ぶため、設定が異なる場合はビン周波数も異なります。Spectrumは表示中の電力平均と最新の寄与窓を読み、任意の時間カーソル位置でFFTを再実行しません。カーソルが最新窓の内側か外側かはSpectrum上の説明で確認できます。Spectrogramは時間カーソルに対応する行を読み、時間カーソルがない場合は最新行を読みます。

上部のStopは全測定器の共通入力履歴・解析済みSpectrum・取り込み済みSTFT画像を保持します。非表示のSpectrumにも停止直前のスナップショットを用意します。停止中は遅着STFTを除外し、同じサンプルを再平均しません。表示範囲・色・配置・カーソルは変更でき、Scope／XYのCH割当、FFTの解析設定とデモ信号の変更は次回開始時に適用します。再開・入力ソース／デバイスの切り替えでは履歴とカーソルを無効化します。操作がない停止中は連続再描画せず、表示寸法が変わらないカーソル移動ではGPUの波形・テクスチャ・表示寸法を転送し直しません。

## 現在の取得・解析・描画の構成

入力キューの消費、共通履歴の更新、デモ生成、Scopeのトリガー・統計、Spectrum FFTは専用測定ワーカーで実行します。STFTへの入力供給も同じワーカーから行います。UIは結果の受信と描画・カーソル読み出しを行い、非表示化や表示更新の停止で測定を止めません。検証条件と残る境界は [PLAN](PLAN.md#現在の実行構造と残る境界) を参照してください。

```text
Audio device → CPAL callback → bounded SPSC → measurement worker ← internal demo
                                               ├→ common f64 history / Scope statistics
                                               ├→ continuous or latest-window Spectrum
                                               ├→ bounded snapshots → UI plots / cursors
                                               └→ selected CH → bounded STFT queue
                                                                        ↓
                                                              continuous STFT worker
                                                                        ↓
                                                              bounded, recycled rows
                                                                        ↓
                                                     UI history → circular GPU texture
```

- **CPAL 0.18**: CoreAudio / WASAPI / ALSAなどのネイティブ入力。デバイス列挙とストリーム作成はUIとは別スレッド。
- **rtrb 0.4**: 固定容量のSPSCリング。音声データのコールバックでロック・待機・メモリ確保・ログ出力を行いません。
- **egui / eframe 0.36 + wgpu**: ネイティブUIとGPUバックエンド。macOSではMetal、他の環境では対応するGPUバックエンドを選択します。
- **専用WGSLシェーダー**: 線分をインスタンスとして送り、アンチエイリアス付きの三角形へGPU側で展開します。波形全体を1回のdraw callで描画します。
- **サンプル集約**: 少数サンプルは直接接続。高密度では物理ピクセルごとの最小値・最大値を保持し、1サンプルの細いスパイクも残します。欠落位置で線を切り、欠落を含む集約区間は描画しません。Scopeのピーク・RMS・peak-to-peakは表示範囲の実サンプルだけから計算し、欠落をゼロで埋めません。描画・転送量は画面幅に比例します。集約と測定のCPU処理は表示サンプル数に比例します。
- **上限のあるメモリ使用**: 入力キューは約0.5秒（最大262,144フレーム）、履歴は2秒分（最大FFT長の32,768フレーム以上）です。溢れたフレーム数を表示し、連番の欠落を固定容量の有効フラグで記録します。容量内の欠落前後のサンプルを保持し、描画とカーソルは欠落位置を実サンプルとして扱いません。トリガーと最新Spectrumは欠落後の連続区間が窓長に達してから再開します。履歴容量以上の欠落やサンプル番号の巻き戻りでは旧履歴を破棄します。
- **測定と表示の分離**: 測定ワーカーが履歴・トリガー・実サンプル統計・Spectrum・STFTへの入力を所有します。3個の容量固定スナップショットを最大30回/秒で渡し、通常の履歴コピーではバッファを再利用します。UIが返却しない間は表示更新だけを省略します。STFTの結果プール飽和は表示行の欠落であり、入力欠落とは別に数えます。Stopは有限の取得済みバッチまでの生サンプルと解析結果を固定し、遅着結果と古い入力世代を除外します。
- **停止時の節電**: 停止中は連続再描画を止め、波形に変更がないフレームはGPUへの波形再転送を省略します。
- **複数プロット**: WGSLパイプラインを共有し、各プロットのGPUバッファ・寸法・更新番号は独立。スペクトルも物理ピクセルごとの極値を保持し、対数軸で密集する狭いピークを残します。
- **FFT**: [RustFFT](https://docs.rs/rustfft/6.4.1/rustfft/)の計画とscratchメモリを再利用します。取得キュー・共通履歴・トリガー・測定値・FFTはf64を標準とします。SpectrumとSpectrogramの「FFT PRECISION」で、それぞれ独立して32-bitの高速FFTを選択できます。DC除去と窓適用の後だけf32へ変換し、窓係数と電力平均はf64を維持します。FFTは実数入力をN/2点の複素変換へまとめ、片側ビンを復元します。GPU表示用のdBFSと座標はf32へ変換します。Spectrumのビン周波数とピクセルの対応は、周波数軸・表示範囲・幅・Fs・FFTサイズを変えたときだけ再計算し、通常のFFT更新とピーク保持で再利用します。Spectrumは既定でN/4 hopのすべての完全窓を測定ワーカーで解析します。Latest windowでは最新の完全窓を最大30回/秒、かつN/4以上の新規サンプルごとに観察します。電力平均とピーク保持は寄与した解析窓ごとに更新し、非表示でも継続します。入力欠落時は平均をリセットし、完全窓から回復します。Performanceには実際の寄与窓数と連続解析の無効窓数を表示します。f64電力結果と窓の由来をスナップショットに保持します。
- **連続STFT**: 別の専用ワーカーで選択した1chを解析します。hopはN/4、FFTサイズ・窓関数・DC除去・対象chはSpectrogram設定から指定します。窓ごとのdBFSを生成し、平均・ピーク保持は適用しません。入力は256フレーム×64ブロック、結果は128行の固定プール（約8 MiB）で再利用します。48 kHz・1,024点・hop 256では約0.68秒分の結果を保持できます。入力ブロックと結果のFs・ch・世代・サンプル位置・欠落情報を保持し、欠落をまたぐ窓や古い世代を表示へ渡しません。チャンネル数が不足した入力フレームはパニックせず破棄し、STFTの入力欠落数へ加算します。Performanceで最新窓の位置とワーカーの欠落数を確認できます。Spectrumとは独立した解析設定を使い、GUI非依存の512行履歴と循環テクスチャへ渡します。

スペクトログラムのR32Floatテクスチャには生のdBFSビンを格納し、最大FFTのNyquistビンまで保持します。1行を4,096列の複数走査線へ分割し、GPUのテクスチャ寸法上限を超えないようにします。変更された行だけを転送し、表示範囲・色・時間座標は描画時に適用します。周波数方向は物理ピクセルが覆うビンの最大値を使い、細いピークを残します。履歴とテクスチャのサイズはFFT設定に応じて固定され、既定の8,192点では各16 MiB、最大32,768点では各40 MiBです。

通常はVSyncを使用します。`--low-latency`ではVSyncを外します。実際の更新頻度はディスプレイ・GPU・OS・入力バッファに依存します。下部の**Performance**メニューにある`UI fps`はUI更新頻度、`Scope prep`・`Worker FFT`・`Spectrum prep`はそれぞれの直近のCPU処理時間で、GPU実行時間ではありません。

## 検証・計測

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh bench --bench waveform --no-default-features
./scripts/cargo.sh bench --bench spectrum --no-default-features
./scripts/cargo.sh bench --bench spectrogram --no-default-features
./scripts/cargo.sh bench --bench xy --no-default-features
./scripts/cargo.sh run --release -- --list-devices
./scripts/cargo.sh run --release -- --audio-smoke
./scripts/cargo.sh run --release -- --audio-smoke --input-device "BlackHole 16ch"
./scripts/cargo.sh run --release -- --stft-smoke --input-device "BlackHole 16ch" --channel 16
./scripts/cargo.sh run --release --features qa -- --multichannel-smoke
./scripts/cargo.sh run --release -- --gpu-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke --compact
```

テストはリング履歴の折り返し、型変換、モノラル／多チャンネル処理、欠落検出用の連番、トリガー、スパイク保持を確認します。ベンチマークは48k・192k・100万サンプルを1920物理ピクセルへ集約するCPU時間を計測します。GPU描画の速度やデバイス入力の遅延を測定するものではありません。

`qa`機能で`--ui-smoke`を使うと、内部テスト信号による画面を撮影できます。`MEASURELAB_UI_SMOKE_SETTINGS=scope`（または`spectrum`、`spectrogram`、`xy`、`workspace`、`collapsed`、`hidden`）を指定すると、その設定パネルの状態で撮影できます。`--compact`との組み合わせで小さい画面も確認できます。`MEASURELAB_UI_SMOKE_XY_PHASE=0`（または`90`、`180`）で同振幅の正弦波を選び、`MEASURELAB_UI_SMOKE_XY_ONLY=1`でXY単独、`MEASURELAB_UI_SMOKE_CHANNELS=1`でモノラル時の表示を確認できます。`MEASURELAB_UI_SMOKE_SCROLL_END=1`はプロット領域を下端へスクロールし、狭い画面の下段を撮影します。

`MEASURELAB_SPECTRUM_PSD=1`は`qa`ビルドでSpectrumをPSDに設定します。`--ui-smoke`やUI計測と組み合わせて、通常幅／狭幅・帯域表示・停止中のモード保持を確認できます。

`MEASURELAB_UI_SMOKE_CURSORS=1`では、欠落を含む同じ有限の入力履歴から全測定器を準備し、ScopeのX位置に固定したA/B時間カーソル・Δt・共通周波数・解析窓・XYの実サンプル組を撮影します。波形・STFTの入力座標を揃えるため、このモードでは通常の循環STFT撮影用の信号を置き換えます。`MEASURELAB_UI_SMOKE_SCOPE_ONLY=1`との組み合わせでScope単独のカーソルとトリガーマーカーを確認できます。

`MEASURELAB_UI_SMOKE_ROUTING=1`はScope／Spectrum／XYを共通の16ch履歴に置き換え、CH 16（0.375 FS peak正弦波）とCH 8（0.25 FS peak、90度位相差）をScopeとXYへ割り当てます。ScopeのA/Bカーソルも表示し、CHラベル・統計・波形と設定パネルの配置を確認できます。Spectrogramは独立した通常の撮影用信号を維持するため、このモードで全測定器の時間対応を検証しません。

```sh
MEASURELAB_UI_SMOKE_ROUTING=1 MEASURELAB_UI_SMOKE_SETTINGS=scope \
    ./scripts/cargo.sh run --release --locked --features qa -- --ui-smoke
```

`--audio-smoke`は入力を2秒間取り込み、フレーム数と全chのピークを確認します。`--input-device`を省略すると既定入力を使います。`--stft-smoke`は同じ入力から連続窓の順序・個数・欠落・ワーカーのCPU時間を確認し、`--channel`は1始まりです。無音でも取得と連続性の検証は可能です。

`--multichannel-smoke`は`qa`機能でのみ使えるBlackHole 16ch専用の確認です。その仮想デバイスの16出力へ異なるビン中心周波数の正弦波（0.125 FS peak）を流し、0.5秒の起動待ち後、2秒間の取得で16入力すべてのch対応・周波数・振幅とCH 16のSTFTを検証します。CH 16／CH 8とその入れ替えで、ScopeのRMS・Peak・P-PとXYの同一フレームのTrace Snapも照合します。起動待ち中のCoreAudio通知は別に出力し、測定区間のストリームエラーや欠落は失敗にします。通常アプリの出力機能ではなく、実デバイスを使うローカルQA用の既知信号です。

`--gpu-smoke`はScope・Spectrum・Spectrogram・XYを準備してから描画し、それぞれの領域をGPUから読み戻します。線分プロットの独立、XYの円と更新番号が同じ場合の線分転送省略に加え、スペクトログラムの折り返し・行の順序・欠落・最大FFTのNyquistビン・表示変更時の再転送省略を検証します。`--ui-smoke`は入力を開始せず、明示的なテスト信号で4画面を短時間開いて閉じます。スペクトログラムの既知信号は周波数を変化させ、履歴の折り返しと意図的な入力欠落を含みます。`qa`機能を有効にすると、その表示を`dist/ui-smoke.png`へ保存します。通常起動時はオーディオ入力、`--demo`指定時は内部信号を使います。GPUやマイクを必要とする確認はCIでは実行しません。

`qa`機能では、2秒の起動待ち後に1〜3,600秒のUIフレーム間隔を記録できます。停止中のフレームは除外し、計測後にUI間隔p95と最大値、VSync待ちを除いたeframeのフレーム処理時間p95、欠落数を出力して終了します。固定容量のヒストグラムで全計測区間を集計し、長時間でも初めの8,192フレームだけに偏りません。p95は0.01 ms刻みの上側へ丸め、200 ms以上の区間がp95に達する場合は実測最大値を上限として報告します。UIの操作イベント・スナップショット受信・各プロットの準備・STFT結果取り込みについて、呼び出しごとのp95と最大値を出します。測定ワーカーとSTFTワーカーのCPU時間はそれぞれ別の合計値として出します。処理ごとのp95を足してフレーム全体のp95にはできません。

以下はBlackHoleのCH 16を選び、10秒間計測する例です。`MEASURELAB_PROFILE_SETTINGS=spectrum`でSpectrum設定を開き、`MEASURELAB_PROFILE_SCREENSHOT=1`で途中の画面を`dist/ui-smoke.png`へ保存できます。デバイスが見つからない、入力にエラーがある、動作中のフレームがない場合は検証を失敗にします。秒数が不正な場合や`qa`なしのビルドで計測を指定した場合もエラーになります。

```sh
MEASURELAB_PROFILE_SECONDS=10 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" MEASURELAB_PROFILE_CHANNEL=16 \
    ./scripts/cargo.sh run --release --features qa
MEASURELAB_PROFILE_SECONDS=10 ./scripts/cargo.sh run --release --features qa -- --demo
```

`MEASURELAB_PROFILE_UI_STALL=1`を追加すると、実際のUIスレッドを1秒止め、入力消費とSpectrum解析の継続・表示更新省略・入力欠落0を確認します。入力キューの保持時間より長い停止です。STFT結果プールが不足した場合の表示行欠落は別に計数します。通常の性能基準値とは条件を分けて扱ってください。

```sh
MEASURELAB_PROFILE_SECONDS=5 MEASURELAB_PROFILE_UI_STALL=1 \
    MEASURELAB_PROFILE_FFT_SIZE=32768 \
    ./scripts/cargo.sh run --release --locked --features qa -- --demo
```

GUIなしの既知入力・平均値の照合と、1ch／2ch／16ch・最大FFT・表示停止・飽和・停止／再開・ストリーム失敗の境界は`measurement`モジュールのテストでも検証できます。

```sh
./scripts/cargo.sh test --locked --lib --no-default-features measurement::tests
```

`MEASURELAB_PROFILE_LIFECYCLE=1`を内部デモのUI計測へ追加すると、Spectrum設定の独立、停止後の遅着結果除外、停止中の解析窓・平均値・生サンプルの保持、デモ設定変更、共通カーソル、表示変更、非表示・単独表示・再表示、再開／入力切り替えでのカーソル無効化、STFTのCH／FFT変更、XYの保持・振幅変更・単独表示・再開を実際のアプリ状態で確認します。`MEASURELAB_PROFILE_IDLE=1`も指定すると、計測用の連続再描画を停止中だけ抑え、待機フレーム間隔を検証します。QAの次段階へ進むための一度のタイマーは残します。計測区間は状態変更を含むため、通常の性能基準値とは別に扱います。

ScopeのX固定カーソルが取得更新・非表示中も新しいサンプルを参照することも、同じライフサイクルQAで確認します。

```sh
MEASURELAB_PROFILE_SECONDS=5 MEASURELAB_PROFILE_LIFECYCLE=1 MEASURELAB_PROFILE_IDLE=1 \
    ./scripts/cargo.sh run --release --features qa -- --demo
```

仮想デバイスを使う停止・再開の統合確認は`MEASURELAB_PROFILE_INPUT_LIFECYCLE=1`で実行します。共通の生サンプル／STFTカーソル、全測定器の保持、遅着結果の除外、停止中の表示・解析設定変更、非表示／再表示、再開時の世代更新、実入力→内部デモ→実入力の切り替えをアプリの入力経路で検証します。`MEASURELAB_PROFILE_SWITCH_DEVICE`を指定すると、最後に別のデバイスへ切り替えます。内部デモのライフサイクルとは別々に実行し、状態変更を含む性能値は通常の基準値と区別します。取得欠落は入力を切り替えてもQA全体で累積します。

このQAではScopeとXYへ最終CH／CH 1を割り当て、停止中に入れ替えた要求が保持中の割当を変えず、再開時に適用されることも確認します。BlackHole 16ch→デモ→BlackHole 2chでは、CH 16を利用不可のまま保持することを確認します。

```sh
MEASURELAB_PROFILE_SECONDS=12 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 MEASURELAB_PROFILE_INPUT_LIFECYCLE=1 \
    MEASURELAB_PROFILE_SWITCH_DEVICE="BlackHole 2ch" MEASURELAB_PROFILE_IDLE=1 \
    ./scripts/cargo.sh run --release --locked --features qa
```

長時間の欠落とプロセスのRSSは`profile-stage2.sh`で記録します。事前にreleaseの`qa`版をビルドし、名前を指定して実行すると、アプリのログと1秒ごとのRSS（KiB）を`dist/stage2-qa/`へ保存します。秒数を省略すると600秒です。RSSは現在の常駐メモリであり、GPUの実行時間やVRAM使用量ではありません。履歴を満たす起動区間と、その後の周回区間を分けて比較してください。画面撮影・並行ビルドなど条件が異なる実行は直接比較しません。

```sh
./scripts/cargo.sh build --release --locked --features qa
MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" MEASURELAB_PROFILE_CHANNEL=16 \
    ./scripts/profile-stage2.sh blackhole16-600
MEASURELAB_PROFILE_SECONDS=120 ./scripts/profile-stage2.sh demo-120 --demo
```

FFT精度と最大窓長を揃えた性能計測には、QA専用の環境変数を使えます。省略時はf64・8,192点です。`f32`は各FFTだけを変更し、共通履歴はf64のままです。VSync有効時と`--low-latency`の間隔を区別して比較します。

```sh
MEASURELAB_PROFILE_SECONDS=10 MEASURELAB_PROFILE_FFT_PRECISION=f64 \
    MEASURELAB_PROFILE_FFT_SIZE=32768 \
    ./scripts/cargo.sh run --release --locked --features qa -- --demo --low-latency
```

## コードの入口

- `src/audio.rs`: CPALデバイス管理、入力コールバック、SPSC転送。
- `src/channel.rs`: 全測定器で使う0始まりの入力CH ID、表示名、Scope／XYの2ch割当と利用可能性。
- `src/measurement.rs`: GUI非依存の入力消費・共通履歴・デモ・Scope統計・Spectrumスケジュール、入力世代・欠落付きの容量固定スナップショット。
- `src/signal.rs`: 固定容量履歴、トリガー、集約、測定。
- `src/cursor.rs`: 入力世代付きの共通A/B時間カーソル、ScopeのX固定と履歴のサンプル固定、Δt、最寄りFFTビン。
- `src/xy.rs`: 任意の2chを同じフレームから読む軌跡、割当付きの観察区間、独立した表示範囲、描画量の上限。
- `src/spectrum.rs`: 窓、FFT、dBFS補正、電力平均、ピーク保持、周波数軸と表示集約。
- `src/stft.rs`: 連続窓のスケジューリング、世代・欠落情報、固定容量キューと結果プール、専用ワーカー。
- `src/spectrogram.rs`: 固定容量のSTFT履歴、サンプル時計の座標、欠落区間。
- `src/spectrogram_gpu.rs` / `src/spectrogram.wgsl`: 循環テクスチャ、行ごとの転送、時間区間と色の描画。
- `src/qa.rs`: 任意に有効化するUI計測とBlackHole 16ch既知信号確認。
- `src/instance.rs`: OSのファイルロックを使う起動制御。
- `src/demo.rs`: 外部出力を伴わない内部デモ信号。
- `src/gpu.rs` / `src/trace.wgsl`: GPUリソースと専用描画パイプライン。
- `src/app.rs`: 測定への操作要求・結果受信、共通操作UIと複数プロット表示。

選定したライブラリの一次資料: [CPAL](https://docs.rs/cpal/0.18.2/cpal/)、[rtrb](https://docs.rs/rtrb/0.4.0/rtrb/)、[eframe](https://docs.rs/eframe/0.36.2/eframe/)、[egui-wgpu](https://docs.rs/egui-wgpu/0.36.2/egui_wgpu/)。

## 既存の検証記録

[2026-10のプロトタイプ検証](validation/PROTOTYPE_2026-10.md) に、数値テスト、GPU読み戻し、画面確認、仮想I/O、性能・欠落・RSSの条件と結果を保存しています。現在の制限と未確認事項は [PLAN](PLAN.md#既存の検証で分かっている範囲) を参照してください。過去の成功は、現在のリビジョンや別の機器での確認を代替しません。

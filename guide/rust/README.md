# MeasureLab — Rust Audio Measurement Lab

CPALで実際のオーディオ入力を取り込み、egui / eframeと`wgpu`で波形・FFTスペクトル・スペクトログラム・XY / Lissajousを同時に描画するRustプロトタイプです。この文書は現在使える操作と構成を説明します。目的・設計原則は [現在の方針](../CURRENT_DIRECTION.md)、実装状態・制限と次の完了条件は [PLAN.md](PLAN.md) を参照してください。

## 起動

Rust 1.95以上と各OSのビルドツールが必要です。開発・検証にはRust 1.99を使用しています。

新しいmacOS／Linux環境では`./scripts/setup_dev_env.sh --install-os-deps --verify`でRust・サイト・文書用ツールを導入できます。前提条件と導入先、手動設定は [開発環境のセットアップ](SETUP.md) を参照してください。

### デバッグ時の簡単な起動

リポジトリのルートにある **Debug-MeasureLab.command** をmacOSのFinderでダブルクリックすると、デバッグビルドを更新して実入力を選ぶ画面で起動します。ターミナルからは以下を使います。

```sh
./scripts/debug.sh
./scripts/debug.sh --demo
./scripts/debug.sh --compact
./scripts/debug.sh --release
```

引数なしでは実入力を選ぶ画面で停止した状態から始まります。デバイスを選んで **Start input** を押します。`--audio`も同じ動作です。`--demo`を明示すると、検証用の`qa`機能を有効にして内部信号で起動します。通常はデバッグシンボルを残すdevビルドを使い、panic時のバックトレースを有効にします。`RUST_BACKTRACE`を指定済みならその値を使います。CPU処理時間などの性能確認には`--release`を使います。

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

**Input source / SAMPLE RATE** で **Device default** またはデバイスが対応する公称レートを選べます。選択肢の上限は768 kHzで、44.1／48／88.2／96／176.4／192／352.8／384／705.6／768 kHzなどから対応する値と、デバイス固有のレートを表示します。入力CH数を維持できる設定を使います。デバイス変更・再取得ではDevice defaultへ戻ります。取得中の変更は新しい入力世代で再開始し、履歴・平均・保持・カーソルをリセットします。停止中の変更は次回Startに適用し、保持結果のFsと時間・周波数軸は変えません。開始時に対応設定を再確認し、失敗時はエラーを表示します。

通常の起動はユーザー単位のファイルロックで重複を防ぎ、2つ目は既に起動中と表示して終了します。意図的に複数起動する場合は`--new-instance`を追加してください。音声を取得するQAコマンドも同じロックを使い、デバイス列挙とGPU読み戻しは対象外です。起動制御は測定コアから分離しています。ロックファイルは残りますが、[OSのファイルロック](https://doc.rust-lang.org/std/fs/struct.File.html#method.try_lock)はプロセス終了時に解放されるため、異常終了後にファイルを手で削除する必要はありません。旧ビルドにはこの制御がないため、旧版との重複は防げません。

通常ビルドの **Input source / Software Loopback** から、マイクを使わず共通入力経路で既知信号を測定できます。条件の詳細は下記のSoftware Loopback節を参照してください。旧QA専用の内部デモは、`qa`機能を有効にしたビルドへ`--demo`を明示して使います。この起動時だけ左側の **Demo signal (QA) / Audio input** で入力を切り替えられます。`qa`ビルドでも、通常起動ではデモの選択肢を表示しません。

```sh
./scripts/cargo.sh run --release --features qa -- --demo
```

`--compact`を追加すると、上下にプロットを配置する小さなウィンドウで起動します。

デモでは周波数、振幅、ノイズを変更し、正弦波／高調波付き正弦波／帯域制限した矩形波を比較できます。CH 2の位相と振幅比も変更できます。**0° / 90° / 180°** ボタンはノイズなし・同振幅の正弦波を設定し、XYの同相・円・逆相を確認できます。CH 2 gainを下げると楕円になります。デモ信号は内部だけで使い、スピーカーには出力しません。

開始／停止は上部に固定しています。左の **Settings** は **Input source / Oscilloscope / Spectrum analyzer / Spectrogram / XY / Lissajous / Channel calibration / Workspace & help** のアコーディオンで、一つの項目を開いて設定します。閉じた項目にも現在値を表示します。Scope／Spectrumの見出しの **Adjust** はその場で開く操作メニューです。Scopeは時間軸・振幅・トレースCH・トリガー、Spectrumは **Display / Analysis** で表示範囲・ピーク保持・PSD帯域とCH・FFT・窓・更新方式・平均を調整できます。クリックを続けてもメニューは開いたままで、外側のクリックまたはEscで閉じます。**Open sidebar settings** は左パネルの該当設定へ移動します。Spectrogram／XYは見出しの **Settings** から同じように移動します。

上部の **View** で **Scope only / Spectrum only / Scope + Spectrum / All instruments** と配置を選べます。**Restore previous view** は最初の切り替え前の表示選択・配置へ戻します。設定ファイルの復元時はこの一時的な復帰先を解除します。切り替えは表示だけを変え、非表示の取得・解析・平均・保持は継続します。数値・カーソルの表示位置とプロット高さは維持し、操作メニューを閉じると波形全体を見られます。

グラフ上部の **Settings** で左パネルを非表示にでき、境界をドラッグすると幅を変更できます。**Collapse all** ですべての項目を閉じられます。**Workspace & help** では複数画面の配置を **Automatic / Side by side / Stacked** から選択し、ショートカットと測定単位を確認できます。4画面の場合、広い画面ではScopeとSpectrumを上段、SpectrogramとXYを下段の2列に配置します。狭い画面では上下4行に並べ、既定の`--compact`ウィンドウでは全体がスクロールなしで収まります。見出し・内側の余白・軸まわりをコンパクトにし、低いプロットでは軸ラベルを間引きます。最低高さで収まらない場合はプロット領域をスクロールできます。幅が不足する場合は左右指定でも上下に配置します。配置・表示選択は測定設定ファイルへ保存・復元できます。アコーディオンの各項目の開閉は現在のセッション内で保持します。

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
| Input source / SAMPLE RATE | Device default／対応する公称Fsを選択。上限768 kHz |
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
| Acquisition / Arm single / Autoset | Auto／Normal／Single、一回取得の再待機、周期信号の時間軸・振幅・トリガー自動調整 |
| ダブルクリック | 時間軸と振幅を初期値へ戻す |
| Scope / Spectrum / Spectrogram / XY | 各測定器の表示切り替え。少なくとも一つを表示。広い画面では左右と上下、狭い画面では上下に配置 |
| Scope / SpectrumのAdjust | 見出しから主要設定を調整。Open sidebar settingsで左パネルの設定へ移動 |
| Spectrogram / XYのSettings | 対象の設定を左パネルで開く |
| View | 単独／Scope＋Spectrum／全表示と配置を選択。Restore previous viewで最初の切り替え前へ戻す |
| グラフ上部のSettings / Collapse all | 左パネルの表示切り替え／設定項目をすべて閉じる |
| File | ファイル選択による設定保存・停止中復元、参照結果読み込み・比較、保持結果のJSON／CSV／PNG保存 |
| Workspace & help | 配置の指定、ショートカット、測定単位と従来のパス指定保存 |
| Save settings / Restore settings | 版付きJSONへ次回Start用の入力・CH・解析・校正と表示設定を保存。復元は入力停止中のみ |
| Export held results | 停止完了後のScope生サンプル・統計とSpectrum全ビンを、取得時の入力・CH・校正・区間・欠落とともに版付きJSONへ書き出す |
| Channel calibration / Queue calibration | CHごとのゲイン・オフセット・物理単位・参照条件を次回Start用に設定 |
| Queue uncalibrated FS | 選択CHを次回Startから未校正FSへ戻す |
| Spectrum Source / points / Window | FFTの入力CH（取得した全chから選択）、サイズ（1,024〜524,288点）、窓関数 |
| Spectrum / Spectrogram FFT PRECISION | 各測定器のFFT精度。既定は64-bit、32-bit (fast FFT)を明示的に選択可能 |
| Live / Continuous / Latest window | Live（既定）は最新の完全窓を最大60回/秒、実測処理時間に応じて観察。ContinuousはN/4全窓。省負荷のLatestは32k以下33 ms／N/4以上、新4サイズ100 ms。非表示でも解析を継続 |
| Bin amplitude / Power spectral density | ビン振幅／PSD。未校正はdBFS／FS²/Hz、校正CHは物理単位 |
| EMA α / Remove DC | 線形値の指数電力平均、FFT前の平均値除去 |
| PSD Power in band / From / To | 指定した両端を含むビン中心のPSD積算。To = 0はNyquist。未校正はFS²とRMS FS、校正CHは単位²とRMS単位を表示 |
| Log Hz / Linear Hz / From / To / Span | 周波数軸・表示範囲。To = 0はNyquist。狭帯域では実ビンを表示 |
| Display floor / Display ceiling / Peak hold / Clear hold | 単位に対応するdB表示範囲、平均後の最大値の保持、保持値のクリア。校正後の正のdB値には天井を上げる |
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

生サンプル・波形軸・トリガー閾値の振幅は、CPALから取得したデジタル音声のフルスケール（FS）です。サンプルレートは取得に使った公称値で、デバイスの時計を校正した実レートではありません。768 kHzは設定上限であり、実際に選べるレートはデバイス・OSの対応範囲に依存します。外部ADCの制御、音声デバイス以外の入力は未実装です。

**Channel calibration** ではCH 1〜16のScope数値読み出しとSpectrumに `y = gain × x(FS) + offset` を適用できます。Gainは物理単位/FS、Offsetは同じ物理単位です。V、mV、Aなどの単位と、基準信号・デバイスレンジ・日付・不確かさなどの参照条件を入力し、**Queue calibration** を押して次回Start用に設定します。負のゲインも使えます。ゲイン0・非有限の係数・空の単位や参照条件は拒否します。**Queue uncalibrated FS** はそのCHの次回用校正を解除します。入力CHの位置をIDとして扱い、トレースを入れ替えても校正は入力CHへ対応します。

ScopeではRMS・Peak・P-Pと時間カーソルの数値に校正を適用します。RMSは各実サンプルを換算してから計算するため、オフセットを含みます。Scopeの波形軸・カーソル点の位置・Fit amplitude・トリガー閾値とSpectrogram／XYはFS基準です。Spectrumは選択CHの校正を振幅・PSD・平均・ピーク保持・カーソル・帯域電力へ適用します。数値と軸の単位をそれぞれ表示します。校正による非有限値やP-Pのオーバーフローは **invalid value** とし、正常値へ置き換えません。欠落や存在しないCHは従来どおり利用不可・部分区間として扱います。

校正のID・版・係数・単位・参照条件は取得世代のスナップショットへ固定します。Scope統計の説明、**Captured readout condition**、Spectrumの校正表示・カーソルの説明で確認できます。取得中や停止後に新しい定義を設定しても、保持中のScope／Spectrum値と校正版は変わりません。Startで適用するまで **Queued for next Start** と区別します。入力ソース・デバイスを選び直したときと **Refresh devices** の再列挙では次回用の校正を解除し、別入力へ持ち越しません。校正は下記の測定設定ファイルへ保存・復元でき、保持したScope／Spectrum結果の書き出しにも含めます。ユーザーが与えた係数による換算であり、ADCや物理基準の校正精度を検証済みとは扱いません。

### 測定設定の保存・復元

上部 **File / Save settings…** で保存先を選びます。**Restore settings…** は入力停止中にファイルを選んで復元します。従来の **Workspace & help / MEASUREMENT SETTINGS** のパス指定も使えます。次回Start用の入力デバイス・CH割当・トリガー・観察幅・Spectrum／Spectrogramの解析設定・PSD帯域・校正定義を版1のJSONへ保存します。取得中の保持結果や未確定の校正エディター入力を保存する操作ではありません。表示選択・配置・軸・表示範囲は別のWorkspaceブロックへ保存します。生サンプル・測定結果・カーソル位置・アコーディオン各項目の開閉は含めません。Software Loopbackの仮想DUT条件、Scope取得モードと実験段階Lock-inの設定も保存します。これらを含まない版1ファイルはAuto・Lock-in無効として読みます。QA専用内部デモは保存対象外です。

既定の保存先はmacOSで `~/Library/Application Support/MeasureLab/measurement-settings.json`、Windowsで `%APPDATA%/MeasureLab/measurement-settings.json`、Linuxで `$XDG_CONFIG_HOME/MeasureLab/measurement-settings.json`（未設定時は `~/.config/MeasureLab/measurement-settings.json`）です。別のパスも指定できます。自動保存・起動時の自動読み込みは行いません。

再起動後、入力を停止した状態で同じパスを指定し、**Restore settings** を押します。Stopの解析完了・デバイス操作・Scopeの保留操作も完了するまで待ちます。復元だけでは取得・出力・記録を開始しません。校正と解析条件は次回Start用に適用し、保持結果のCH・公称Fs・入力世代・校正版は維持します。軸や観察幅などの表示操作は保持した生サンプルから再表示します。復元中はStartを受け付けません。

入力は名前や列挙順でなくCPALの安定したデバイスIDを照合します。不在・重複ID、CH数の変化、指定レートの非対応、Device defaultで保存した既定Fsの変化では復元全体を拒否し、別のデバイスやレートへ置き換えません。接続を戻して **Refresh devices** を行い、再度復元してください。対応しない版・旧形式・不正値・64 KiBを超えるファイルや、セッション内で既知の校正ID／版と異なる定義も拒否します。保存失敗では以前のファイルを維持し、成功・失敗はパネルと下部の **Settings status / Settings error** から確認できます。デバイスIDの保証範囲はOS・バックエンドに依存します。条件付きの検証と未確認範囲は [設定保存の検証](validation/SETTINGS_2026-10.md) を参照してください。

### Software Loopbackと実験段階Lock-in

通常ビルドの **Input source / Software Loopback** を選び、Startを押すと2chの同期f64入力を生成します。CH 1はREF、CH 2は既知ゲイン・位相・整数サンプル遅延・DC・雑音を適用した正弦波DUTです。雑音は指定RMSの独立な一様乱数です。周波数・振幅・REFの有効／無効と応答周波数ずれも設定でき、条件は次回Startに適用します。公称Fsは44.1／48／96／192 kHzです。整数遅延は正弦波を解析的に遅らせ、開始直後の未到達応答は0とします。スピーカーや物理出力は使いません。

上部の **Lock-in** で独立した測定画面を追加できます。**View / Lock-in only** は単独表示、**Scope + Lock-in** は波形と並べた表示です。左側の **Lock-in amplifier / Open Lock-in display** からも単独表示を開けます。表示を隠しても有効なロックイン演算は継続します。

**Lock-in amplifier / Enable demodulator** または画面下の **Demodulate** で有効化し、Signal／Reference CH、REF周波数ヒント、時定数、積分サンプル数、REFのAC RMS閾値を指定します。画面下の **REF / Filter…** でも周波数・Tracking・時定数とプリセット・積分窓を調整できます。取得中の変更は平均をリセットして再整定し、停止中の変更は次回Start用です。保持中は取得時の条件を表示し、変更があると **Next Start settings changed** を併記します。REFは常に入力サンプルを使用します。Trackingはヒントの±10%に限定し、REFのAC RMS不足・単一正弦波への適合率98%未満・一窓3周期未満は無効になります。既定のREF閾値は0.001 FS RMSです。同じCHをREF／応答へ選ぶ自己検査も可能です。

画面の **R / θ**、**X / Y**、**All four** で大きな数値表示を切り替えます。数値下のバーは表示専用の自動スケールで、入力感度や測定演算を変更しません。FS／校正後の単位、peak定義、REF周波数、Gain、取得時のτ・積分窓を併記します。Gainの単位は応答単位／REF単位です。**REF VALID**、**SETTLING** と10τの進捗、**REF LOST / UNSTABLE**、入力欠落・無効状態、**HOLD** を区別し、無効値はゼロで代用せず「—」とします。**Measurement details** で整数サンプル区間、REF強度・適合率、処理窓数・欠落数、校正ID／版を確認できます。Lock-inの表示選択・座標表示は測定設定JSONのWorkspaceへ保存され、旧版1ファイルでは非表示・R／θが既定です。

基本波のX／Yは同じ非重複整数窓で測ったREF位相を補正してから二段の複素EMAで平均します。周期Hannの重み付きDC／sin／cos適合を使い、DCオフセットと校正オフセットはACから除外します。校正ゲインはREFと応答の両方へ適用します。Rはpeak振幅、正のY／位相は応答の進みです。複素応答/REFも平均してGainを表示します。フィルター係数は `1 − exp(−N/(Fs×τ))`、整定判定は連続有効入力10τで、UI時刻・壁時計には依存しません。窓平均も応答帯域・遅延に寄与し、τだけで帯域を決めたとは扱いません。欠落・非有限・REF喪失では古い平均と数値を破棄し、回復後に整定し直します。

**Lock-inは実験段階です。仮想系の精度確認は必須ですが、実機でREF・タイミングを含めて使用できるまで完了としません。** 高調波REF、広範囲PLL、異なる入出力時計の補正や物理出力は未実装です。旧版との対応・許容差・残る実機確認は [Lock-inの検証](validation/LOCKIN_2026-10.md) を参照してください。

### Scopeの取得とAutoset

**Adjust / Acquisition** または左のOscilloscopeでモードを選びます。Autoは従来の最新区間観察です。Normalは指定エッジの交差を取得サンプルごとに検出し、前20%・後80%の完全な整数区間だけを更新します。トリガー待機中は最後の捕捉値を明示して保持し、まだ捕捉していないときは波形を代用しません。Normal／SingleでFree runを選ぶと次回の取得にはRising edgeを設定します。

Singleは最初の有効区間を捕捉して共通入力を自動停止します。**Arm single** またはStartで新しい世代を開始し、一回取得を待ち直せます。Scopeの区間は専用バッファで保持するため、UI更新の合間の単発現象も捕捉し、共有履歴の周回後も失いません。Spectrumは独立しているため、Singleが短く終了した場合はFFT窓が未充填になることがあります。

**Autoset** は選択したトリガーCHの直近最大200 msの生サンプルから安定した周期・振幅を評価し、約3周期の観察幅、FS振幅軸、立ち上がり・中央レベルを設定します。DC・無信号・低振幅・クリップ・不安定な周期・欠落・存在しないCHでは設定を変えず理由を表示します。Normal／Singleの停止中は捕捉条件を固定し、時間軸・トリガーの変更を次回Startへ適用します。

### Spectrumの測定定義

524,288点は実入力の窓長です。48 kHzではΔf ≈ 0.091553 Hz、周期HannのRBW ≈ 0.137329 Hz、窓時間 ≈ 10.9227秒、ContinuousのN/4 hop ≈ 2.7307秒です。開始・解析条件変更・欠落後は完全な窓の充填を待ち、未取得分をゼロで代用しません。Liveの高速観察でも完全窓の充填時間と窓時間は変わりません。Latestの100 ms観察では隣接窓が約99.1%重なります。同じEMA αでも解析間隔が変われば秒単位の応答が変わります。BIN幅・RBW・周波数読み値の精度・入力時計の誤差は区別します。Spectrogramは独立した1,024〜32,768点の上限を維持します。大きなFFTの基礎検証は [大きなFFTの検証](validation/LARGE_FFT_2026-10.md)、Liveと描画性能の条件・結果は [描画更新の検証](validation/SPECTRUM_PERFORMANCE_2026-10.md) に保持します。

未校正のSpectrumの既定モード **Bin amplitude** は片側ビン振幅のdBFSです。窓のcoherent gainを補正し、ビン中心の1 FS peak正弦波を0 dBFSとします。DCとNyquistのビンは2倍しません。振幅ビンを積算して雑音電力とは扱いません。**Δf** はFs/N、**RBW** は窓の等価雑音帯域です。48 kHz・8,192点・HannではΔf ≈ 5.86 Hz、RBW ≈ 8.79 Hz、窓時間 ≈ 170.7 ms。ピークは最大ビンの値なので、1 kHzの信号が1002.0 Hzのビンに表示される場合があります。

ビンの間にある信号は複数のビンに分散するため、ピークの読み値が実振幅より低くなることがあります。

**Power spectral density** は片側PSDをFS²/Hzで測定し、表示は10 log10(PSD / 1 FS²/Hz)の **dB re FS²/Hz** です。周期窓w、正規化前のFFTをXとすると、PSDは`c × |X|² / (Fs × Σw²)`です。cはDC／Nyquistで1、その他で2です。Remove DCは窓を掛ける前に各窓の算術平均を引きます。振幅からPSDへ切り替えると平均・保持をリセットします。Spectrogramの振幅表示は変更しません。

PSDの **Power in band** は、From〜Toの両端を含む中心周波数のビンを選び、`ΣPSD[k] × Δf`をf64で計算します。To = 0は取得時のNyquistです。実際に含めた最初／最後のビン周波数、電力FS²、平方根のRMS FSを表示します。電力とRMSは微小値も読める指数表記を使います。DC／Nyquistも全Δfの重みで含めます。半端なビンの補間や台形積分は使いません。範囲が不正、範囲内にビンがない、完全なPSD窓がない場合は利用不可とし、別範囲の値を代用しません。帯域指定と表示Spanは独立し、帯域を変えても平均はリセットしません。

単一窓の全帯域積算はParsevalにより`Σw²(x−μ)² / Σw²`に一致します（DC除去なしはμ = 0）。Rectangularでは生サンプルの平均二乗、他の窓では窓付きの平均二乗です。定常正弦波・雑音の電力評価と短い過渡の窓位置依存を区別し、Scopeの観察区間のRMSと常に同一とは扱いません。ビン間正弦波では漏れを含む十分な帯域を選んで評価します。dBm・負荷インピーダンス換算は未実装です。

Spectrumの校正CHは、振幅を物理単位peak、PSDを単位²/Hz、帯域積算を単位²とRMS単位で読み出します。dB表示はそれぞれ `20 log10(振幅 / 1 単位peak)`、`10 log10(PSD / 1 単位²/Hz)` です。たとえばVでは **dB re 1 V peak** と **dB re 1 V²/Hz** を使い、未校正CHは従来のdBFS／FS²/Hzを維持します。負のゲインも電力へ正しく反映します。Remove DCなしでは `y = gain × x + offset` を窓掛け前に計算し、校正したDCが窓によって隣接ビンへ広がることも含みます。Remove DCありでは `gain × (x − mean(x))` をf64で計算し、オフセットを相殺してから窓掛け・任意のf32変換を行います。全帯域PSD積算は校正した信号の窓付き平均二乗に対応します。Spectrumワーカーの入力、校正値、FFT電力が非有限なら **Invalid FFT window** とし、平均と保持をリセットして次の有効な完全窓から回復します。この無効窓数と入力欠落数を別に表示します。条件と許容差は [Spectrum校正の検証](validation/SPECTRUM_CALIBRATION_2026-10.md) に保持します。

平均は **EMA α = 1/指定値** による指数的な線形電力平均です。最初の完全窓で初期化し、次の窓から`P ← P + α(Pnew − P)`を適用します。α = 1では最新窓だけを使います。処理窓数と最初〜最新の寄与区間を結果に保持しますが、均等な積算回数や区間全体の一様なRMSを意味しません。Live（既定）は全サイズでN/4の進行を要求せず、最大60回/秒の最新窓観察です。解析総時間の2倍と16.67 msの大きい方を周期の下限にし、遅い処理では直ちに延長、回復時は徐々に短縮します。対象は新しい終端の完全窓だけで、描画回数や表示の開閉に依存しません。ContinuousはN/4の全完全窓を処理します。Liveと省負荷のLatestは観察時点の最新窓だけを使い、過渡の捕捉を保証しません。Latestの32,768点以下は33 ms以上かつN/4以上、新4サイズは100 msでN/4の制限を外します。カーソルの説明で最新窓・寄与区間・CH・設定・入力世代・欠落を確認できます。

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

上部のStopは全測定器の共通入力履歴・解析済みSpectrum・取り込み済みSTFT画像を保持します。Stopは有限の入力終端を固定し、SpectrumとLock-inの処理完了まで停止処理中の状態を表示します。UIは待機中も操作でき、Continuousは終端までの全完全窓、Latestは最後の完全窓を一度だけ処理します。停止中は遅着STFTを除外し、同じサンプルを再平均しません。表示範囲・色・配置・カーソルは変更でき、Scope／XYのCH割当、FFTの解析設定とデモ信号の変更は次回開始時に適用します。再開・入力ソース／デバイスの切り替えでは履歴とカーソルを無効化します。操作がない停止中は連続再描画せず、表示寸法が変わらないカーソル移動ではGPUの波形・テクスチャ・表示寸法を転送し直しません。

### 保持結果の書き出し

**Stop** の解析完了を待ち、上部 **File / Export results JSON… / CSV… / PNG…** で保存先を選べます。従来のパス指定は、**Workspace & help / HELD MEASUREMENT RESULTS** で保存先を確認して **Export held results** を押します。入力開始前、取得中、StopやScopeの条件更新・設定復元が未完了の間は書き出せません。書き出し後は同じ場所に成功・失敗を表示し、上部の **Export status / Export error** から開けます。既定の保存先は設定ファイルと同じディレクトリの `measurement-results.json` です。ファイルは同じディレクトリの一時ファイルへの書き込みと同期後に置換し、失敗時は以前のファイルを残します。

結果の形式は `format = measurelab-results`、`version = 1` のJSONです。復元用の測定設定JSONとは別の形式で、**File / Load reference result…** から参照として読み込み、**Compare with reference** で現在の保持結果と並べて確認できます。入力世代・取得時のデバイスID／名前／入力形式・実際に選ばれた公称Fs・CH数を保持し、次回用の入力選択や解析設定・校正で保持結果を再ラベルしません。CH IDは0始まり、サンプル区間は開始を含み終端を含みません。サンプル時計は公称値です。

Scopeは書き出し時に表示する整数区間・観察サンプル数・トリガー条件・補間した横位置と、2本の割当CHの生f64サンプル（FS）、生統計・校正後の統計を保持します。配列の位置 `i` は `sample_range.start + i` に対応し、欠落位置は `null`、存在しないCHは配列全体を `null` として状態を付けます。未取得・欠落・非有限の校正結果を正常なゼロと扱いません。校正はID・版・ゲイン・オフセット・単位・参照条件を含み、物理量は `gain × raw_fs + offset` から再現できます。Autoの停止後の観察幅・トリガー変更は保持サンプルから新しい区間を選ぶため、書き出すScope区間・条件もその選択に対応します。Normal／Singleの捕捉区間・トリガー条件は停止後も固定し、編集は次回Startに適用します。

Spectrumは独立した最新FFT区間・解析設定・モード・観察間隔・Δf・RBW・校正・EMA係数／処理窓数／寄与区間・ピーク保持の対象スペクトル数／寄与区間を含みます。全ビンのf64線形値と保持値を保存し、配列の位置 `k` の周波数は `k × bin_width_hz` です。DCとNyquistを含み、振幅は平均したビン電力の平方根（単位peak）、PSDは平均した密度（単位²/Hz）です。表示用f32のdB値・表示下限へ変換せず、真のゼロは線形値0のまま保存します。PSDの指定帯域は書き出し時の範囲と両端を含む対象ビン・電力・RMSを保持します。帯域が不正・ビンを含まない場合や振幅モードでは帯域結果は `null` です。未取得／非有限のSpectrumは状態を付け、ビン・平均・保持・帯域の値を `null` とします。

取得時に有効化したLock-inは、X/Y・R（peak）・REFに対する進み位相・Gain、REF周波数／生AC RMS／正弦波適合率／校正後peak、τ・積分窓・追従設定・閾値、両CHの校正と単位を含みます。平均の寄与区間と最新完全窓は独立した整数区間です。整定中の値にはSettling状態を付け、未充填・REF喪失・欠落・非有限では数値を `null` とし、旧値を保存しません。停止中の次回用CH・Fs・校正・フィルター変更は保持結果を変更しません。保存・参照読み込みでは単位・状態・完全窓数・整定時間・区間・REF診断・X/Y/R/位相の整合を検証します。Lock-inを含まない旧版1の結果JSONも読み込めます。

ScopeとSpectrumの区間は同時刻とは限らず、EMAとピーク保持の寄与区間は一様な重みや連続的な捕捉を示しません。取得欠落、Scope区間内の欠落、Spectrum入力欠落／無効窓／非有限窓／観察省略、ワーカー開始以来の表示スナップショット省略、入力失敗を分けます。Spectrogram、XY、カーソル、全CHの長時間記録やSpectrum窓の全生入力は含めません。書き出し用データは固定の上限を持つ保持区間とFFT全ビンから一度だけコピーし、JSON化・ファイルI/Oは専用ワーカーで行います。書き込み中に入力を再開しても書き出し対象は変わりません。検証条件は [結果書き出しの検証](validation/EXPORT_2026-10.md) を参照してください。

参照結果は一件・128 MiB以下に制限します。版・配列長・CH・単位・校正・整数区間・有限値・欠落・Spectrum状態の整合を全体検証し、不正ファイルを一部だけ適用しません。読み込みは取得を開始せず、現在の保持結果を上書きしません。**Keep held result as reference** で現在の結果を参照へ固定することもできます。比較画面はScope生FS波形と統計、Spectrum線形ビンとPSD帯域・条件を併記します。Scopeの統計差は同じCH・単位、PSD帯域差は同じFs・CH・単位・解析設定・モード・対象ビンの場合だけ表示します。独立記録のサンプル時計を同期した波形差として扱いません。

CSVは条件を含む `metadata_json` 行に続き、Scopeの整数サンプル番号・公称秒・生f64・校正値・単位・欠落、Spectrumのビン番号・周波数・線形値・保持値を出力します。PNGは1600×1160の独立したレポートで、主要統計・CH・単位・区間・FFT／窓／EMA・校正・欠落を付けます。PNG内にも数値配列を除いた条件を埋め込みます。精密な数値の正本はJSON／CSVです。

Lock-inを含むCSVには `lockin` 行を追加し、整数区間・CH・完全窓数・欠落数・f64のX/Y/R/位相/Gain・REF診断値・単位・状態を出力します。無効値は空欄です。参照比較ではLock-inの取得条件・状態・校正版と数値を左右に表示し、両結果がValidで、公称Fs・CH・REF／フィルター設定・両CHの校正が一致し、入力失敗がない場合だけX/Y/R/Gainと位相の差を表示します。位相差は±180°へ折り返します。独立記録の入力時計は同期しません。PNGの描画対象はScope／Spectrumです。確認範囲は [Lock-in結果再利用の検証](validation/LOCKIN_RESULTS_2026-10.md) を参照してください。

## 現在の取得・解析・描画の構成

入力キューの消費、共通履歴の更新、デモ生成、Scopeのトリガー・統計は専用測定ワーカーで実行します。選択CHの固定長f64ブロックを、独立したSpectrum／STFTワーカーへ渡します。FFT計画・履歴・平均・保持はSpectrumワーカーが所有し、取得はFFT完了を待ちません。UIは結果の受信と描画・カーソル読み出しを行い、非表示化や表示更新の停止で測定を止めません。検証条件と残る境界は [PLAN](PLAN.md#現在の実行構造と残る境界) を参照してください。

```text
Audio device → CPAL callback → bounded SPSC → measurement worker ← internal demo
                                               ├→ common f64 history / Scope statistics
                                               ├→ bounded blocks → Spectrum worker (continuous / latest)
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
- **上限のあるメモリ使用**: 入力キューは約0.5秒（最大262,144フレーム）、Scope／XYの全CH履歴は2秒分（最低32,768フレーム）です。溢れたフレーム数を表示し、連番の欠落を固定容量の有効フラグで記録します。容量内の欠落前後のサンプルを保持し、描画とカーソルは欠落位置を実サンプルとして扱いません。トリガーと最新Spectrumは欠落後の連続区間が窓長に達してから再開します。履歴容量以上の欠落やサンプル番号の巻き戻りでは旧履歴を破棄します。
- **測定と表示の分離**: 測定ワーカーが履歴・トリガー・実サンプル統計・Spectrum／STFTへの入力を所有します。3個の容量固定スナップショットを最大30回/秒で渡し、通常の履歴コピーではバッファを再利用します。UIが返却しない間は表示更新だけを省略します。Spectrumは別の3個の結果プールを使い、解析結果の更新番号が変わったときだけ配信・再集約します。STFTの結果プール飽和は表示行の欠落であり、入力欠落とは別に数えます。Stopは有限の取得済みバッチまでの生サンプルと解析結果を固定し、遅着結果と古い入力世代を除外します。
- **停止時の節電**: 停止中は連続再描画を止め、波形に変更がないフレームはGPUへの波形再転送を省略します。
- **複数プロット**: WGSLパイプラインを共有し、各プロットのGPUバッファ・寸法・更新番号は独立。スペクトルも物理ピクセルごとの極値を保持し、対数軸で密集する狭いピークを残します。
- **FFT**: [RustFFT](https://docs.rs/rustfft/6.4.1/rustfft/)の計画とscratchメモリを再利用します。取得キュー・共通履歴・トリガー・測定値・FFTはf64を標準とします。SpectrumとSpectrogramの「FFT PRECISION」で、それぞれ独立して32-bitの高速FFTを選択できます。DC除去と窓適用の後だけf32へ変換し、窓係数と電力平均はf64を維持します。FFTは実数入力をN/2点の複素変換へまとめ、対称なビンを一緒に復元して複素乗算とtwiddle表を半減します。GPU表示用のdBFSと座標はf32へ変換します。Spectrumはピクセル列ごとの連続ビン範囲をキャッシュし、dB配列の極値をまとめます。狭い範囲では二分探索で対象ビンだけを処理し、保持dBは新しい最大値だけで更新します。ビン周波数とピクセルの対応は、周波数軸・表示範囲・幅・Fs・FFTサイズを変えたときだけ再計算し、通常のFFT更新とピーク保持で再利用します。Spectrumは専用ワーカーで、既定のLive観察とN/4全窓のContinuousを選べます。Latest windowの新4サイズは100 msごとに新しい終端の完全窓を観察し、N/4の進行は要求しません。32,768点以下は従来の33 ms／N/4以上の周期観察を維持します。電力平均とピーク保持は寄与した解析窓ごとに更新し、非表示でも継続します。入力欠落時は平均をリセットし、完全窓から回復します。Performanceには実際の寄与窓数と連続解析の無効窓数を表示します。f64電力結果と窓の由来をスナップショットに保持します。
- **連続STFT**: 別の専用ワーカーで選択した1chを解析します。hopはN/4、FFTサイズ・窓関数・DC除去・対象chはSpectrogram設定から指定します。窓ごとのdBFSを生成し、平均・ピーク保持は適用しません。入力は256フレーム×64ブロック、結果は128行の固定プール（約8 MiB）で再利用します。48 kHz・1,024点・hop 256では約0.68秒分の結果を保持できます。入力ブロックと結果のFs・ch・世代・サンプル位置・欠落情報を保持し、欠落をまたぐ窓や古い世代を表示へ渡しません。チャンネル数が不足した入力フレームはパニックせず破棄し、STFTの入力欠落数へ加算します。Performanceで最新窓の位置とワーカーの欠落数を確認できます。Spectrumとは独立した解析設定を使い、GUI非依存の512行履歴と循環テクスチャへ渡します。

スペクトログラムのR32Floatテクスチャには生のdBFSビンを格納し、最大FFTのNyquistビンまで保持します。1行を4,096列の複数走査線へ分割し、GPUのテクスチャ寸法上限を超えないようにします。変更された行だけを転送し、表示範囲・色・時間座標は描画時に適用します。周波数方向は物理ピクセルが覆うビンの最大値を使い、細いピークを残します。履歴とテクスチャのサイズはFFT設定に応じて固定され、既定の8,192点では各16 MiB、最大32,768点では各40 MiBです。

通常はVSyncを使用します。`--low-latency`ではVSyncを外します。実際の更新頻度はディスプレイ・GPU・OS・入力バッファに依存します。下部の**Performance**メニューにある`UI fps`はUI更新頻度、`Scope prep`・`Worker FFT`・`Spectrum prep`はそれぞれの直近のCPU処理時間で、GPU実行時間ではありません。

## 検証・計測

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --doc --all-features
./scripts/cargo.sh bench --bench waveform --no-default-features
./scripts/cargo.sh bench --bench spectrum --no-default-features
./scripts/cargo.sh bench --bench spectrogram --no-default-features
./scripts/cargo.sh bench --bench xy --no-default-features
./scripts/cargo.sh run --release -- --list-devices
./scripts/cargo.sh run --release -- --audio-smoke
./scripts/cargo.sh run --release -- --audio-smoke --input-device "BlackHole 16ch"
./scripts/cargo.sh run --release -- --stft-smoke --input-device "BlackHole 16ch" --channel 16
./scripts/cargo.sh run --release -- --stft-smoke --input-device "BlackHole 16ch" --channel 16 --sample-rate 192000
./scripts/cargo.sh run --release --features qa -- --multichannel-smoke
./scripts/cargo.sh run --release -- --gpu-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke
./scripts/cargo.sh run --features qa -- --ui-smoke --compact
```

テストはリング履歴の折り返し、型変換、モノラル／多チャンネル処理、欠落検出用の連番、トリガー、スパイク保持を確認します。ベンチマークは48k・192k・100万サンプルを1920物理ピクセルへ集約するCPU時間を計測します。GPU描画の速度やデバイス入力の遅延を測定するものではありません。

`cargo test`のbenchは各条件1回の動作確認で、出力された時間を性能評価に使いません。`cargo bench`は従来どおり反復計測します。数値テストの精度・FFTサイズ・窓・f64／f32の許容差は維持し、120／600秒の実時間負荷評価は下記の専用手順で実行します。

`qa`機能で`--ui-smoke`を使うと、内部テスト信号による画面を撮影できます。`MEASURELAB_UI_SMOKE_SETTINGS=scope`（または`spectrum`、`spectrogram`、`xy`、`workspace`、`collapsed`、`hidden`）を指定すると、その設定パネルの状態で撮影できます。`--compact`との組み合わせで小さい画面も確認できます。`MEASURELAB_UI_SMOKE_XY_PHASE=0`（または`90`、`180`）で同振幅の正弦波を選び、`MEASURELAB_UI_SMOKE_XY_ONLY=1`でXY単独、`MEASURELAB_UI_SMOKE_CHANNELS=1`でモノラル時の表示を確認できます。`MEASURELAB_UI_SMOKE_SCROLL_END=1`はプロット領域を下端へスクロールし、狭い画面の下段を撮影します。

`MEASURELAB_UI_SMOKE_VIEW=scope`（または`spectrum`、`pair`）はViewの単独／2表示、`MEASURELAB_UI_SMOKE_ADJUST=scope`（または`spectrum`、`analysis`）はScopeの操作メニュー／SpectrumのDisplay／Analysisを開いた状態で撮影します。設定パネルの表示／非表示と組み合わせて重なり・幅・高さを確認できます。

`MEASURELAB_SPECTRUM_PSD=1`は`qa`ビルドでSpectrumをPSDに設定します。`--ui-smoke`やUI計測と組み合わせて、通常幅／狭幅・帯域表示・停止中のモード保持を確認できます。

`MEASURELAB_UI_SMOKE_STAGE3F=1`は通常のSoftware Loopbackを起動・停止し、Scope統計、FFTと実験段階Lock-inの理論値、設定・参照結果の保存／読み込み／復元／再測定、CSV／PNG、Singleの480サンプル捕捉と未充填512k／Lock-inをアプリ状態で照合します。Lock-inの保持値・取得条件が停止中の次回用CH・Fs・校正・τ変更で変わらないことと、条件が一致する整定済み結果の比較も確認します。保存先は `dist/stage3f-*` です。続いて別プロセスで `MEASURELAB_UI_SMOKE_REPLAY=1` を指定すると前回ファイルから復元して再測定し、アプリ再起動後の再現を確認します。`MEASURELAB_UI_SMOKE_COMPARE=1` は比較画面を開きます。ネイティブ選択ダイアログはこのQAの自動操作対象外です。

`MEASURELAB_UI_SMOKE_LOCKIN=polar` は通常のSoftware Loopback経路で750 Hz・0.0625 FS peak・30°を測定してStopし、Lock-in単独画面を撮影します。`cartesian`／`all`／`pair` はX／Y・4値・Scopeとの併用、`settling` は整定中、`ref-loss` はREF喪失、`held-edit` は保持した結果と次回Start用設定の区別、`live-edit` は取得中のτ変更と再整定、`source-change` は入力ソース切り替え時の旧値破棄を確認します。`--compact` で狭幅にします。撮影先は `dist/ui-smoke.png` です。

GUIの条件付きの結果・画面寸法・未確認事項は [Lock-in GUIの確認](validation/LOCKIN_GUI_2026-10.md) に保持します。

```bash
MEASURELAB_UI_SMOKE_STAGE3F=1 target/release/measurelab --ui-smoke --new-instance
MEASURELAB_UI_SMOKE_STAGE3F=1 MEASURELAB_UI_SMOKE_REPLAY=1 \
    target/release/measurelab --ui-smoke --compact --new-instance
```

`MEASURELAB_UI_SMOKE_SETTINGS_RESTORE=1`は合成16chデバイスIDの設定ファイルを `dist/settings-restore-qa.json` へ保存・読み込みし、不在入力・校正衝突・取得中の復元拒否、復元中のStart拒否、保持データ・条件の不変性、開始準備でのCH 16維持をアプリ内で検証します。実入力は開始しません。

`MEASURELAB_UI_SMOKE_EXPORT=1`は内部QAの保持結果を `dist/results-export-qa.json` へ書き出します。取得中／設定復元中の拒否と、書き込み要求後の次回用CH・FFT・校正・公称Fsの編集で、ファイル内の保持値・条件が変わらないことを検証します。`MEASURELAB_UI_SMOKE_CALIBRATION=1`や`MEASURELAB_SPECTRUM_PSD=1`と併用できます。

`MEASURELAB_PROFILE_EXPORT=dist/results-profile.json`は実時間QAの有限Stop結果を専用I/Oワーカーで書き出し、ファイルの全値・条件がスナップショットと一致することを確認します。終端の書き出しと照合はUI性能の計測区間外です。

```sh
MEASURELAB_UI_SMOKE_SETTINGS_RESTORE=1 ./scripts/debug.sh --ui-smoke --low-latency
```

`MEASURELAB_UI_SMOKE_CALIBRATION=1`はScopeのTrace 1の入力CHへ4 V/FS・オフセット0.5 Vの内部QA校正を適用します。`MEASURELAB_UI_SMOKE_SETTINGS=calibration`で校正パネルを開き、通常幅／狭幅でFSの波形軸・Vの数値・未校正CHのFS・A/Bカーソルを確認できます。`MEASURELAB_UI_SMOKE_SETTINGS=spectrum`では校正したビン振幅、`MEASURELAB_SPECTRUM_PSD=1`との組み合わせではPSD・V²・RMS Vを確認できます。物理校正の検証ではありません。

```sh
MEASURELAB_UI_SMOKE_CALIBRATION=1 MEASURELAB_UI_SMOKE_SETTINGS=calibration \
    ./scripts/cargo.sh run --release --locked --features qa -- --ui-smoke
```

`MEASURELAB_UI_SMOKE_CURSORS=1`では、欠落を含む同じ有限の入力履歴から全測定器を準備し、ScopeのX位置に固定したA/B時間カーソル・Δt・共通周波数・解析窓・XYの実サンプル組を撮影します。波形・STFTの入力座標を揃えるため、このモードでは通常の循環STFT撮影用の信号を置き換えます。`MEASURELAB_UI_SMOKE_SCOPE_ONLY=1`との組み合わせでScope単独のカーソルとトリガーマーカーを確認できます。

`MEASURELAB_UI_SMOKE_ROUTING=1`はScope／Spectrum／XYを共通の16ch履歴に置き換え、CH 16（0.375 FS peak正弦波）とCH 8（0.25 FS peak、90度位相差）をScopeとXYへ割り当てます。ScopeのA/Bカーソルも表示し、CHラベル・統計・波形と設定パネルの配置を確認できます。Spectrogramは独立した通常の撮影用信号を維持するため、このモードで全測定器の時間対応を検証しません。

```sh
MEASURELAB_UI_SMOKE_ROUTING=1 MEASURELAB_UI_SMOKE_SETTINGS=scope \
    ./scripts/cargo.sh run --release --locked --features qa -- --ui-smoke
```

`--audio-smoke`は入力を2秒間取り込み、フレーム数と全chのピークを確認します。`--input-device`を省略すると既定入力を使います。`--stft-smoke`は同じ入力から連続窓の順序・個数・欠落・ワーカーのCPU時間を確認し、`--channel`は1始まりです。両方で`--sample-rate HZ`（上限768000）を指定でき、省略時はデバイス既定です。無音でも取得と連続性の検証は可能です。

`--multichannel-smoke`は`qa`機能でのみ使えるBlackHole 16ch専用の確認です。その仮想デバイスの16出力へ異なるビン中心周波数の正弦波（0.125 FS peak）を流し、0.5秒の起動待ち後、2秒間の取得で16入力すべてのch対応・周波数・振幅とCH 16のSTFTを検証します。CH 16／CH 8とその入れ替えで、ScopeのRMS・Peak・P-PとXYの同一フレームのTrace Snapも照合します。起動待ち中のCoreAudio通知は別に出力し、測定区間のストリームエラーや欠落は失敗にします。通常アプリの出力機能ではなく、実デバイスを使うローカルQA用の既知信号です。

`--gpu-smoke`はScope・Spectrum・Spectrogram・XYを準備してから描画し、それぞれの領域をGPUから読み戻します。線分プロットの独立、XYの円と更新番号が同じ場合の線分転送省略に加え、スペクトログラムの折り返し・行の順序・欠落・最大FFTのNyquistビン・表示変更時の再転送省略を検証します。`--ui-smoke`は`qa`ビルド専用で、入力を開始せず、明示的なテスト信号で4画面を短時間開いて閉じ、`dist/ui-smoke.png`へ保存します。スペクトログラムの既知信号は周波数を変化させ、履歴の折り返しと意図的な入力欠落を含みます。通常起動時はオーディオ入力を選んだ停止状態、`qa`ビルドの`--demo`指定時は内部信号を使います。通常ビルドで`--demo`や`--ui-smoke`を指定すると、検証用ビルドが必要な旨を表示して終了します。GPUやマイクを必要とする確認はCIでは実行しません。

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

512kを含む性能計測では`MEASURELAB_PROFILE_FFT_SIZE`はSpectrumへ適用し、Spectrogramは最大32,768点に制限します。`MEASURELAB_PROFILE_STFT_SIZE`で独立した窓長、`MEASURELAB_PROFILE_SPECTRUM_MODE=live`（既定）／`continuous`／`latest`で更新方式を選べます。Liveの実際の描画更新数・更新間隔はUIフレーム数とは別に`Spectrum drawing`へ出力します。`MEASURELAB_PROFILE_UI_STALL=1`は完全窓の充填後に最大（1秒、3 hop）の間UIを止めます。512k・48 kHzでは約8.192秒です。

`MEASURELAB_PROFILE_KNOWN_OUTPUT=1`はQA専用で、指定したBlackHole 2ch／16chの仮想出力だけへ各CHで異なる0.125 FS peak正弦波を流します。測定終了時にSpectrumの振幅／PSD、CH、整数終端とContinuousの予定窓数を照合します。物理出力、通常のGenerator、Software Loopbackの実装ではありません。

```sh
MEASURELAB_PROFILE_SECONDS=600 MEASURELAB_PROFILE_DEVICE="BlackHole 2ch" \
    MEASURELAB_PROFILE_FFT_SIZE=524288 MEASURELAB_PROFILE_STFT_SIZE=8192 \
    MEASURELAB_PROFILE_SPECTRUM_MODE=continuous MEASURELAB_PROFILE_KNOWN_OUTPUT=1 \
    ./scripts/profile-stage2.sh large-fft-continuous-600
```

`MEASURELAB_PROFILE_DEMO_BIN_TONE=1`と`--demo`は、750 Hz・0.125 FS peak・雑音0・2chの90度位相差へQA入力を固定し、終端の振幅／PSDとContinuousの窓数を照合します。内部デモの確認であり、外部I/OやSoftware Loopbackの検証ではありません。`MEASURELAB_PROFILE_SPECTRUM_ONLY=1`でSpectrum 1個だけを表示できます。非表示の測定演算は継続します。`MEASURELAB_PROFILE_LARGE_LIFECYCLE=1`（512k、40秒以上）では通常の非同期Stop、保持、次回設定、再開、CH 2／PSD／Latest、非表示と再表示を検証します。

`MEASURELAB_PROFILE_LIFECYCLE=1`を内部デモのUI計測へ追加すると、Spectrum設定の独立、停止後の遅着結果除外、停止中の解析窓・平均値・生サンプルの保持、デモ設定変更、共通カーソル、表示変更、非表示・単独表示・再表示、再開／入力切り替えでのカーソル無効化、STFTのCH／FFT変更、XYの保持・振幅変更・単独表示・再開を実際のアプリ状態で確認します。`MEASURELAB_PROFILE_IDLE=1`も指定すると、計測用の連続再描画を停止中だけ抑え、待機フレーム間隔を検証します。QAの次段階へ進むための一度のタイマーは残します。計測区間は状態変更を含むため、通常の性能基準値とは別に扱います。

ScopeのX固定カーソルが取得更新・非表示中も新しいサンプルを参照すること、停止中に次回用の校正を編集してもScope／Spectrumの保持条件が変わらず、再開時に適用されることも、同じライフサイクルQAで確認します。Viewの単独／2表示／全表示と元の配置への復帰では、保持したf64結果・条件・カーソルが変わらないことを照合します。

```sh
MEASURELAB_PROFILE_SECONDS=5 MEASURELAB_PROFILE_LIFECYCLE=1 MEASURELAB_PROFILE_IDLE=1 \
    ./scripts/cargo.sh run --release --features qa -- --demo
```

仮想デバイスを使う停止・再開の統合確認は`MEASURELAB_PROFILE_INPUT_LIFECYCLE=1`で実行します。共通の生サンプル／STFTカーソル、全測定器の保持、遅着結果の除外、停止中の表示・解析設定変更、非表示／再表示、再開時の世代更新、実入力→内部デモ→実入力の切り替えをアプリの入力経路で検証します。`MEASURELAB_PROFILE_SWITCH_DEVICE`を指定すると、最後に別のデバイスへ切り替えます。内部デモのライフサイクルとは別々に実行し、状態変更を含む性能値は通常の基準値と区別します。取得欠落は入力を切り替えてもQA全体で累積します。

`MEASURELAB_PROFILE_SAMPLE_RATE=48000`は実入力の開始レートを指定します。上記ライフサイクルで`MEASURELAB_PROFILE_SWITCH_SAMPLE_RATE=192000`を追加すると、保持中に次回用Fsを変更し、保持値のFsを維持した後、再開したSpectrum／STFTが新しいFsを使うことを検証します。デバイス切り替えを指定した場合はDevice defaultへ戻ります。`MEASURELAB_PROFILE_SETTINGS=input`と`MEASURELAB_PROFILE_SCREENSHOT=1`で入力設定を撮影できます。

このQAではScopeとXYへ最終CH／CH 1を割り当て、停止中に入れ替えた要求が保持中の割当を変えず、再開時に適用されることも確認します。BlackHole 16ch→デモ→BlackHole 2chでは、CH 16を利用不可のまま保持することを確認します。

```sh
MEASURELAB_PROFILE_SECONDS=12 MEASURELAB_PROFILE_DEVICE="BlackHole 16ch" \
    MEASURELAB_PROFILE_CHANNEL=16 MEASURELAB_PROFILE_INPUT_LIFECYCLE=1 \
    MEASURELAB_PROFILE_SWITCH_DEVICE="BlackHole 2ch" MEASURELAB_PROFILE_IDLE=1 \
    ./scripts/cargo.sh run --release --locked --features qa
```

長時間の欠落とプロセスのRSSは`profile-stage2.sh`で記録します。事前にreleaseの`qa`版をビルドし、名前を指定して実行すると、アプリのログと1秒ごとのRSS（KiB）、psのCPU使用率と累積CPU時間を`dist/stage2-qa/`へ保存します。秒数を省略すると600秒です。macOSの入力実行中はタイマー精度を要求するOS activityを保持し、Stop／失敗／終了で解除します。`MEASURELAB_PROFILE_KEEP_AWAKE=1`で計測中だけcaffeinateによるアイドルシステム／画面スリープ抑止を付けられます。抑止の有無を測定条件へ記録します。RSSは現在の常駐メモリであり、GPUの実行時間やVRAM使用量ではありません。履歴を満たす起動区間と、その後の周回区間を分けて比較してください。画面撮影・並行ビルドなど条件が異なる実行は直接比較しません。

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
- `src/settings.rs`: 版付き測定設定・校正と表示設定のJSON、全体検証、デバイスID照合、容量制限付き読み込み・原子的保存、専用I/Oワーカー。
- `src/results.rs` / `src/result_image.rs` / `src/workspace_io.rs`: 容量制限と整合検証付き参照読み込み、f64 CSV、PNG、ネイティブファイル選択とI/O。
- `src/acquisition.rs`: サンプル時計のNormal／Single捕捉とAutoset。
- `src/loopback.rs` / `src/lockin.rs` / `src/lockin_worker.rs`: 通常ビルドの仮想DUTと実験段階の同期REF Lock-in、固定容量の独立演算。
- `src/app/lockin_panel.rs`: Lock-inのR／θ・X／Y・4値表示、参照状態・整定・保持、測定条件の操作と表示専用のバー。
- `src/export.rs` / `src/file_io.rs`: 保持したScope／Spectrumと測定条件の版付きJSON、欠落・無効状態とf64線形値、専用I/Oワーカー、設定保存と共有する原子的ファイル置換。
- `src/calibration.rs`: ID・版・参照条件付きのCH校正、Scope実サンプルの換算・RMS／Peak／P-P、非有限値の無効化。
- `src/measurement.rs`: GUI非依存の入力消費・共通履歴・デモ・Scope統計・解析への供給、入力世代・欠落付きの容量固定スナップショット。
- `src/signal.rs`: 固定容量履歴、トリガー、集約、測定。
- `src/cursor.rs`: 入力世代付きの共通A/B時間カーソル、ScopeのX固定と履歴のサンプル固定、Δt、最寄りFFTビン。
- `src/xy.rs`: 任意の2chを同じフレームから読む軌跡、割当付きの観察区間、独立した表示範囲、描画量の上限。
- `src/spectrum_worker.rs`: 選択1chの大きな履歴、Live／Continuous／Latest、固定容量入力・結果プール、非同期Stopの終端処理。
- `src/spectrum.rs`: 窓、FFT、dBFS補正、電力平均、ピーク保持、周波数軸と表示集約。
- `src/stft.rs`: 連続窓のスケジューリング、世代・欠落情報、固定容量キューと結果プール、専用ワーカー。
- `src/spectrogram.rs`: 固定容量のSTFT履歴、サンプル時計の座標、欠落区間。
- `src/spectrogram_gpu.rs` / `src/spectrogram.wgsl`: 循環テクスチャ、行ごとの転送、時間区間と色の描画。
- `src/qa.rs`: 任意に有効化するUI計測とBlackHole 16ch既知信号確認。
- `src/instance.rs`: OSのファイルロックを使う起動制御。
- `src/demo.rs`: `qa`機能／単体テスト専用の、外部出力を伴わない内部デモ信号。
- `src/gpu.rs` / `src/trace.wgsl`: GPUリソースと専用描画パイプライン。
- `src/app.rs`: 測定への操作要求・結果受信、共通操作UIと複数プロット表示。

選定したライブラリの一次資料: [CPAL](https://docs.rs/cpal/0.18.2/cpal/)、[rtrb](https://docs.rs/rtrb/0.4.0/rtrb/)、[eframe](https://docs.rs/eframe/0.36.2/eframe/)、[egui-wgpu](https://docs.rs/egui-wgpu/0.36.2/egui_wgpu/)。

## 既存の検証記録

[2026-10のプロトタイプ検証](validation/PROTOTYPE_2026-10.md) に、数値テスト、GPU読み戻し、画面確認、仮想I/O、性能・欠落・RSSの条件と結果を保存しています。現在の制限と未確認事項は [PLAN](PLAN.md#既存の検証で分かっている範囲) を参照してください。過去の成功は、現在のリビジョンや別の機器での確認を代替しません。

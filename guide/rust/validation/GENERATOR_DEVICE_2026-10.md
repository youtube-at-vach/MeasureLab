# Generator実デバイス出力の条件付き検証

対象：2026-10-13、`03622c6f`を基点とする`codex/generator-device-output`の未コミット作業ツリー。Rust 1.99.0、macOS 14.8.9（23J631）、x86_64、Metal／AMD Radeon R9 M290X。最終差分のrelease QAソース・実行ファイルSHA-256は`dist/generator-qa/verified-source-sha256.json`で、UAC-232／BlackHole 16chの通常幅と連続QAを再実行した。以前のrelease QAは`source-sha256.json`、配置修正後の入力先行dev QAは`final-source-sha256.json`に分離する。狭幅・その他表示の以前の実機試験を最終差分の再実測とは扱わない。内部演算・通常GeneratorのCPAL経路を使い、既存QAの固定周期出力を使わない。

## 基準と範囲

* 公称48 kHz、f32、750 Hz。GEN 1は0.1 FS peak、GEN 2は0.05 FS peak・+30°。入力・出力のFSは未校正。
* BlackHole 2chはOUT 1／2、16chはOUT 1／16。REFは入力CH 1、応答は最終CH。未割当出力CHの受信サンプルはゼロを照合する。
* UAC-232はユーザーが用意したL–L／R–RのTRS物理ループ。出力→入力の絶対ゲイン・電圧・実時計・DAC／ADC遅延を保証しない。
* Spectrumは8,192点・Rectangular・f64・平均1・Continuous。Lock-inは同期REF追従・4,096サンプル積分・二段フィルターτ=5 ms。定常の完全窓から比較する。
* f32変換は3e-8 FS以下、整数はsignedの`2^(bits-1)`基準・ゼロ方向切り捨てと端点飽和の1 LSB以内。unsignedはmidpointを加える。全12 PCM形式を内部数値テストで照合し、外部I/Oの確認形式はf32のみ。
* BlackHoleのR／Spectrum振幅／整数周期RMSは3e-8 FS以内、位相1e-6°以内、REF周波数1e-7 Hz以内。物理Lock-inは同じ実入力窓の独立したDC＋sin＋cos最小二乗適合と比較し、R誤差`peak × 0.002 + 2e-6 FS`未満、相対位相誤差0.05°未満とする。

## 確認済みの条件

| 対象 | 結果 |
| --- | --- |
| PCMと可変コールバック | 全12形式の量子化・端点・無音、1／2／16ch、可変長1／511／17／1,024／3／4,096、2^53超の連番、未消費の応答キューでも生成・有限フェードが継続。失敗後のunsigned出力もmidpointの無音 |
| 制御・設定 | Stopと接続中のStartの共通フェンス、古い未送信Startと新しい編集の混在、OFF復元、旧版2内部設定の既定Target、版1の読み込み、選択した出力CH／Fs／PCM以外への暗黙の切り替え拒否。不在・重複出力IDと形式不一致は内部回帰で拒否を確認 |
| 期限付き解放 | ソフトウェア上でストリーム失敗、2秒のコールバック停止、Stopから500 ms後も終端ゼロがない条件を照合。実際のUSB切断とは分ける |
| BlackHole 2ch／16ch | Scope／Spectrum／Lock-in、無音CH、1秒のUI受信停止、入力Stop中の出力継続、JSON／CSV読み戻し、出力OFFでの設定復元を確認。R=0.050000000561176 FS、相対位相30.0000001029°。独立適合との差はR約5e-15 FS、位相約8.2e-12° |
| UAC-232 | 同じ操作と独立生入力照合を通常幅・狭幅・Spectrum／Lock-in表示で確認。最終release QAの通常幅ではR=0.0297644374 FS、相対位相29.9854583°、独立適合との差はR約−1.55e-7 FS・位相約−4.47e-4°で許容差内。出力設定0.05 FSとの差は未校正のアナログ経路の条件であり、演算誤差と混同しない |
| GUI配置 | 1440×860／900×660の論理寸法、2倍の画像で撮影。狭幅の出力先欄の過大なレイアウトを修正し、選択CHの周波数・振幅・位相・停止操作が収まることを画像で確認。DPI切り替えは未実施 |

最終差分の数値・条件・画像・ログは`dist/generator-qa/{uac232-verified-scope,blackhole16-verified-scope}/`、以前の条件は`{blackhole2,blackhole16,uac232,uac232-spectrum,uac232-lockin,uac232-final-scope,uac232-final-narrow}/`へ分離する。保持した通常外部入力の結果に、内部接続用の出力区間を付けない。出力条件は設定JSONとQAの`device-output.json`へ別に記録し、出力連番と入力連番を同じサンプル位置と扱わない。

## 実装差分の回帰確認

最終差分に対する`cargo fmt`、全ターゲット・全機能Clippy、GUIなし178件、通常183件＋起動回帰2件、全ターゲット・全機能192件＋起動回帰3件、doc test、デスクトップreleaseビルドを実行して成功した。benchは`cargo test`による各条件1回の動作確認で、反復性能の合格には使わない。Rust 1.95の全ターゲット・全機能`check --locked`も成功した。ログは`dist/generator-qa/checks/*-verified.log`に保持する。

Ruff check／format check、変更したMarkdownのlint、日英RustマニュアルのMkDocs strictビルドは成功した。数値・ビルドの成功で、下記の実機連続試験の失敗を取り消さない。

## 失敗と未完了事項

最初の短時間物理QAは数値照合後に、入力停止の応答前に保存しようとして失敗した。QAの停止待ちを修正して再実行し、保存・復元まで通過した。

連続GUIの起動直後の自動Startでは入力のCoreAudio underrun通知で失敗した。初回を途中終了し、次の試行は失敗で終了した。入力開始を最初のGUI描画から2秒後へ移した短時間試行では入力／Spectrum／STFTの欠落0とUI停止中の継続を確認したが、出力失敗でREFを喪失し、最終独立照合に失敗した。入力開始から0.5秒後に出力を開始する順序でも、1秒のUI停止中に48,128入力フレーム・21 FFT窓の継続を確認した後、入力のCoreAudio underrun／overrun通知で失敗した。ログは`dist/stage2-qa/generator-uac232-input-first.log`に保持する。いずれも300秒完走・100回編集・正常な有限Stopの成功として扱わない。通知を無視する処理や、REF喪失時の正常値代用は加えていない。

最終差分のrelease QAでも、ビルド・別の音声試験を並行実行せず、`caffeinate`で画面・システムのアイドルスリープを抑えた8秒の連続GUI試行を行った。入力開始から0.5秒以上後の出力開始、1秒UI停止中の47,616入力フレーム・21 FFT窓の継続後、入力のCoreAudio underrun／overrunで終了した。終了コード101、最終独立照合と有限Stop監査は未完了。ログ・RSSは`dist/stage2-qa/generator-uac232-isolated{.log,-rss.csv}`に保持する。

連続GUIの入出力開始時通知の原因・安定化、300秒と100回編集の完走、外部結果への出力履歴・遷移と入力窓の対応、実USB切断、出力コールバックCPUのp95、DPI切り替え・別プロセス復元、他Fs・PCM・OS・機器は未確認。段階4.5全体は未完了で、段階5への進行条件を満たしたとは扱わない。

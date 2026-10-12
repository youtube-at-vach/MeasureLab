# Generator 内部接続の検証

## 対象と条件

2026-10-12。基点`6c6feaad`（Generatorコア`b946c874`を含む）へ加えたGenerator GUI・`output.rs`・共通入力・保存条件の作業差分を対象とする。macOS 14.8.9、Intel Core i5-4690・4コア・16 GiB、Metal／AMD Radeon R9 M290X、ローカルRust 1.99.0を使用した。通常ビルドの機能を`qa`の統合ハーネスから操作し、QA専用デモ・物理出力を励振の代用にしない。

出力／入力は同じ整数時計の2ch f64・公称48 kHz。GEN 1は750 Hz・0.125 FS peak、GEN 2は750 Hz・0.0625 FS peak・+30°。Scopeは512サンプル、Spectrumは8,192点・Rectangular・Continuous・平均1回、Lock-inはREF CH 1／Signal CH 2・τ=5 ms。出力の開始遷移後に完全窓と整定を待ち、入力欠落・失敗0を要求する。

## 確認結果

* 独立生成ワーカーの実フレームを固定容量転送で共通測定へ渡し、Scope RMS・Spectrum振幅・Lock-in R／θ／REF周波数を照合した。許容差は振幅・RMS 1e-8 FS、位相1e-6°、REF周波数1e-7 Hz。
* UIでの結果・出力状態の受信を1秒停止しても取得・生成が24,000フレーム以上進むこと、入力Stop後も出力が進むことを確認した。入力Stopの有限結果は出力の継続や後の設定復元で変化しない。
* JSON書き出し・読み戻しの全値一致とCSV書き出し、設定復元後の入力停止・出力OFFを確認した。設定／結果は版2、版1の読み込みは数値回帰で確認する。CSVのmetadata_jsonにも整数区間の出力条件を残す。
* 共通コアの決定的試験では48,000サンプル目にGEN 2を0.03125 FS peak・−90°へ変更し、Spectrum／Lock-inの寄与区間が48,480以降から再開することと数値一致を確認した。出力Stop後も取得中の新しい無音フレームを供給し、Scope／Spectrumがゼロ、Lock-inがREF喪失になることを確認した。
* 条件履歴は最大128区間。遷移・欠落・退役した区間や異なる相対carrier位相を同じ定常励振として比較しない。2^53超の整数連番と入力・表示転送の飽和を数値回帰に含める。
* eguiの入力イベントでEscの取消し、Enter／Tabの確定、上下キーによる編集中の値の増減を照合した。未編集の表示文字列を確定しても適用済みf64値を小数3桁へ丸めない。
* 1440×860 pointの2カード＋Scope／Spectrum／Lock-inと、900×660 pointのSettings＋CHタブを撮影した。描画画像は2倍のpixel寸法。狭幅でも両CHの状態・選択CHの3値・全出力停止はスクロールなしで表示でき、Scopeは下のスクロール領域で観察する。既存の4表示UIも撮影して回帰確認した。

保持結果の例はRMS 0.08838834764831843／0.04419417382415922 FS、Lock-in R 0.06250000000000026 FS peak、位相29.99999999999998°。入力／Scope欠落0・入力失敗なし。表示更新の省略は測定欠落と分けて記録した。CSVのmetadata_jsonから読み戻した出力条件がJSONと一致することも確認した。

GUIなし171件、通常ビルド176件＋起動2件、全ターゲット・全機能185件＋起動3件のテスト、doc-test、全ターゲット・全機能Clippy、fmt、通常デスクトップreleaseビルドが成功した。Ruff、Markdown lint、新旧マニュアルのMkDocs strictビルドも成功した。全ターゲットのbenchは各条件1回の動作確認で、反復した性能評価として扱わない。

初回は数値QAに成功したが画像読み戻しを受信できなかった。同じ環境での再実行では数値QAとMetalの画面撮影が成功した。画面OFFとの因果関係を単独に切り分けた確認ではない。

## 再実行と成果物

```sh
./scripts/cargo.sh build --locked --features qa
MEASURELAB_UI_SMOKE_GENERATOR=scope target/debug/measurelab --ui-smoke
MEASURELAB_UI_SMOKE_GENERATOR=narrow target/debug/measurelab --ui-smoke
MEASURELAB_UI_SMOKE_GENERATOR=spectrum target/debug/measurelab --ui-smoke
MEASURELAB_UI_SMOKE_GENERATOR=lockin target/debug/measurelab --ui-smoke
```

画面撮影は`dist/ui-smoke.png`、保存設定・JSON／CSVと検証ログは`dist/generator-qa/`。各画面は同ディレクトリの`ui-normal.png`／`ui-narrow.png`／`ui-spectrum.png`／`ui-lockin.png`／`ui-regression.png`へ保持した。Generatorの複数画面の再実行は`caffeinate -d -i`で画面・システムのアイドルスリープを抑止した。画像・大量ログはGitへ追加しない。

## 未確認の境界

CPAL Generator出力、f32／整数PCM変換、BlackHole／UAC-232と新Generatorの接続、出力校正・実時計・物理精度は未実装または未確認。300秒の新出力連続運転、100回以上の通常GUI編集、操作応答・GPU負荷の性能目標、DPI切り替え・Windows／Linuxの実機確認も未実施。段階4.5の内部接続の確認であり、段階4.5全体の受け入れ完了ではない。

# クイックスタート

## ソースから起動

Rust版を含むチェックアウトとRust 1.95以降が必要です。統合先はmainへの切り替えまでは`rewrite/rust`です。macOSではXcode Command Line Tools、LinuxではALSA／X11／Waylandの開発ライブラリ、WindowsではMSVCとVisual Studio C++ Build Toolsを用意します。詳細はリポジトリの`guide/rust/SETUP.md`を参照してください。

リポジトリのルートで実行します。

```sh
cargo run --release --locked
```

macOS／Linuxのローカルセットアップ環境では`./scripts/cargo.sh run --release --locked`も使えます。通常は入力を停止した状態で起動します。

## 機器なしで最初の測定

1. **Input source** で **Software Loopback** を選びます。これは通常ビルドで使え、物理出力は行いません。
2. 上部の開始ボタンで取得を開始し、**View** で **Scope + Spectrum** を選びます。
3. 各グラフの **Adjust** で時間軸・振幅、FFT・窓・CHを調整します。最初は既定の8,192点を使ってください。
4. **Stop** で結果を保持し、カーソルやRMS、ピーク、PSDの帯域値を読みます。
5. **File** から設定と保持結果を保存します。JSONは測定条件を含む正本、CSVは数値の再利用、PNGは表示の共有に使います。
6. 再起動後、停止中に設定を復元し、参照JSONを読み込んで再測定結果と比較できます。設定復元だけで取得は始まりません。

524,288点では48 kHzで完全窓の取得に約10.92秒必要です。Live表示を速くしても、この観測時間は短くなりません。ContinuousはN/4ごとの全窓を解析し、Live／Latestの最新窓観察は過渡の捕捉を保証しません。

## 実入力を使う

入力デバイスと対応するサンプルレートを選び、**Start input** を押します。macOSでは起動したアプリ／ターミナルへのマイク許可が必要です。CH数やFsは機器に依存します。CH校正を使う場合も、Scopeの波形軸とトリガーはFSのままです。

停止中に入力・解析・校正を編集した場合は、次回Start用の条件です。保持中の結果の取得条件は変わりません。入力変更・再開時は古い世代の結果を混ぜず、新しい履歴を取得します。

## 実験段階のLock-in

Software LoopbackでREFと応答を用意し、Lock-in表示のREF／Signal CHを指定します。X/YとRはpeak単位、正の位相は応答の進みです。整定中・REF喪失・欠落を有効な測定値と扱わないでください。実機確認は未完了です。

Stopの解析完了後、**File** からLock-inの条件・校正・状態とf64値をJSON／CSVへ保存できます。無効値はJSONの `null`、CSVの空欄になります。参照比較には両結果の数値・取得条件を表示し、整定済みで公称Fs・CH・REF／フィルター設定・校正が一致する場合だけ数値差を表示します。PNGの表示対象はScope／Spectrumです。

確認範囲と未実装機能は [概要](index.md) を参照してください。

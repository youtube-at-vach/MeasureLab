# 0022: セッションID校正を取得結果と両Qt表示へ接続する

日付: 2026-10-02。状態: 評価用境界。公開API/製品校正形式/採用の決定ではない。

## 判断

006-Eの後段ID校正を、007-Aの保存replay/BlackHole解析ownerで使う。
セッション設定のprofileをChannelId/device/portへ明示的に結び付け、streamを開く前に検証する。
profile配列の順序では対応を決めない。実結果区間を `applied_interval` へ記録する。
通常結果とTrigger結果は同じセッション設定を使い、共有raw FFT/履歴/平均を変更しない。

Qtは結果の校正snapshot/V RMS/dBVだけを読み、値/校正を計算しない。
選択チャンネルの校正状態・係数・revisionを表示し、未校正絶対値はnull/reasonを保持する。
グラフはFSを維持し、SPL/clock情報を補完しない。保持結果はセッション/設定変更後も不変。

## 範囲と代償

今回の完了単位はセッション設定→取得/Trigger→不変result→両Qt表示/診断CSV・JSON。
Qtからprofileを編集・適用する配送と、製品保存操作/互換/非同期workerは別の作業票に残す。
diagnostic係数を実deviceの校正証拠にしない。profile期限や測定基準もこの設定では扱わない。

Triggerは既存owner APIの未校正resultからcapture metadataを受け、同じrawへ校正resultを生成する。
追加FFTはないが、profile有りでは一時的に二つのowned resultを生成する負荷がある。
独立callback/queueは変更しない。最初のBlackHole反復で取得queueのgapを検出したため、
liveのCSV診断保存はstream/graph停止後に完全JSONを一件ずつ再読込して行う。
取得中は従来のJSON保存だけを行い、CSV失敗は停止後もfailureとして返す。
保存replayの診断保存は同期I/Oであり、負荷/定常性能の合格には数えない。
JSON/CSVのペアcommitを保証せず、保存失敗を成功へ置き換えない。

## 検証と引き継ぎ

[検査手順](../../native/calibration-display.md)のrunnerへ期待値は渡さず、元bytesだけを通す。
保存port/profile逆順、異なる係数、disabled/欠けたprofile、実入力bytesの全配列を独立oracleへ照合する。
既存Triggerのpending/retry/raw共有/hold/gap/解除/寿命検査を維持し、9言語の実ラベル/サイズも検査する。
Rust testは誤binding/重複/不正profileの取得前拒否、別profile再開/破棄後の保持不変性、完全再読込を確認する。
NumPy-only破損検査と独立Native CIを追加する。結果/失敗log/未確認範囲は[進捗](../status.md)に記録する。

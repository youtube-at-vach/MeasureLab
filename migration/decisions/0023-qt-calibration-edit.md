# 0023: Qtの校正profile編集を解析ownerへ配送する

日付: 2026-10-02。状態: 評価用境界。製品設定/公開ABI/採用の決定ではない。

## 判断

0022のsession ID校正を、取得中に両Qtから更新する一件のtyped mailboxへ拡張する。
ChannelId/device/portを実取得設定へ照合し、解析ownerだけが全profileを原子的に置換する。
enqueueと適用完了を区別し、busy/旧世代/逆順revision/停止と、不正profileの非破壊拒否を検査する。
校正操作は取得世代/FFT key/履歴を変更しない。新resultへ後段校正を適用し、完成resultを再校正しない。
同じ取得区間のraw FFTは共有する。capture metadataと実適用区間は各owned resultに残す。
Triggerの完全resultは実取得区間でprofileを解決して一度だけ生成し、未校正resultからの再生成を避ける。
従来の未校正APIは空profile providerへ委譲し、pending/gapではproviderを呼ばない。

Qtでは取得設定からchannelとbindingを読んで編集し、保持中のresultのprofileを現在設定と混同しない。
有効・無効と係数/revisionの編集、未指定channelへの追加を共通ダイアログに置く。
表示/校正計算は既存resultに任せ、9言語を製品翻訳JSONで管理する。

## 範囲と代償

編集の適用は現在セッションだけ。再開/Backend再生成は初期設定を使い、その制約をUIにも示す。
製品保存操作/旧設定互換/非同期保存/再起動維持は別の作業票へ残す。
純粋ID校正の既存契約・fixture・数値許容差は変更しない。callbackへのmutex/Qt/I/O追加も行わない。
profile変更の通常resultとreceiptを診断保存する追加負荷がある。
8chの短時間検査で取得gapとTrigger encode中のFFT停止を検出したため、通常結果を最大8件、
Trigger診断を最大8件の不変snapshot/receipt/bytesとして保持し、完全JSON保存を停止後へ移した。
同じTrigger世代/revision/statusのretry診断は最初の一件にまとめ、容量超過は明示failureにする。
小さな校正操作receiptは取得中に保存する。製品用async保存workerは未実装。
live CSVも停止後にsaved snapshotを一件ずつ再読込するため、最終設定が空でも過去校正を保持できる。
診断保存の失敗を隠さず、定常/負荷下/長時間性能や製品保存の合格へ数えない。

## 検証と引き継ぎ

[再検査手順](../../native/calibration-edit.md)のrunnerは元保存/取得bytesだけをQtへ渡す。
期待profileを独立にChannelIdから構成し、変更前後の全配列と来歴をNumPyへ照合する。
同じ区間のraw ID/FFT件数、旧result不変、CSV完全再読込、実翻訳/サイズ/PNG、停止/再開/破棄を確認する。
Rustでbusy/世代/容量/不正profile/原子的拒否/停止を、Pythonで証拠破損の拒否を検査する。
Native CIへ保存比較を追加し、実施結果と未確認範囲は[進捗](../status.md)へ記録する。

# 0030: 製品読込みを独立readerと参照表へ接続する

日付: 2026-10-03。状態: 評価用実装。[native parser](../../native/product-import.md)と
[Qt手順](../../native/qt-import.md)を参照。採用・schema確定ではない。

## 判断

旧トレースは完全な取得snapshotと区別し、製品JSON/CSV pair/明示CSV specを
同じreaderへ配送する。読込済みprofileを現在のdevice/sessionへ適用しない。
独立した参照表で元値と軸/単位/校正を確認し、取得中のline/heatmapへ暗黙に重ねない。

受付のpath/spec/formatをtyped JSONで検査し、専用workerが全file/parser/preview処理を所有する。
queued+readingは合計2件、receipt履歴16件、retire中も含むreader session最大8個。
全productをworkerに保持し、GUIには元indexを選んだ数値とdescriptorだけを渡す。
previewは最大8192 scalar/1 MiB、各textは256文字まで。長い単位/IDは短縮せず拒否する。
数値tokenを文字列として渡し、JavaScriptのJSON再生成でも負のゼロと元値を保持する。

同じBackendでの最新受付だけを公開する。取消/失敗した最新要求や受付終了によって
古い完成結果を表示しない。操作IDはBackend再生成後もprocess内で再利用しない。
取消はqueuedだけ、readingは実際のloaded/failedを残し、閉じた画面へ公開しない。

全productの置換・Drop、readerのjoinをGUIから切り離す。
QObject破棄はclose/cancelを行い、終了threadへ所有権を移す。
アプリ終了時に終了threadを回収し、受付を実完了と混同しない。
保存workerとreaderは別queueであり、取得owner・現在の校正設定を共有しない。

## 根拠と未確認

保存fixtureと独立readerの全配列比較、元bytesの数値oracle、実Qt表示/終了、
決定的なreader停止による容量/取消/fenceテストを使う。実行結果は[status](../status.md)を正本とする。
旧fileの欠けたTimebase/ChannelIdを現在の取得条件から補う方法は採用しない。

参照表は表示用samplingを明示する。line/heatmap、全点cursor/zoom、importからの
再エクスポート、再起動profile維持、byte/RSS予算、長時間/負荷、他OS/実window managerは後続。
この範囲の成功だけでMIG-007/008やRust/QMLの採用を完了にしない。

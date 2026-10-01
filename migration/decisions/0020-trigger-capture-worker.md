# 0020: 取得ownerの非消費Trigger capture

日付: 2026-10-01。コア契約v0.1・元fixture・許容差・Rust/QML採用判断は変更しない。

## 問題

006-Cに履歴のquery、006-Eに元triggerを持つ不変result、005に取得ownerはあるが、
これらを一つのtrigger captureへ接続していなかった。
通常graphのscheduleは単調な区間を要求し、過去窓を再投入すると逆順・重複として拒否する。
この制限を外して最新mailboxや独立平均へ過去窓を流すと、通常表示の位置と平均を壊す。

## 決定

* `Acquisition::capture_trigger()`から既存履歴を非消費でqueryする。floor/pre/post、
  分数残差、pending/missing区間、世代fenceを再実装しない。
* 完成窓だけをowned snapshot/不変resultへ接続する。元TriggerEventを保持し、
  受信host時刻を測定位置や推定clock原点へ置き換えない。
* 同じ通常key/区間がcacheにあればraw FFTを共有する。cache missは既存FFTを
  一時graphで評価し、通常購読へ公開しない。一時graphを回収し、追加raw cacheは一件に制限する。
* 同じrawを共有した各capture結果にも別のresult IDを割り当て、
  request/host時刻等の違うmetadataを同一の不変result IDとして保存しない。
* restart/stopはworkerの追加cacheを解除する。確定済み外部snapshotはその後も参照可能。
* この段階はN≤4096の同期解析owner API。pendingの再試行は呼出し側の明示操作とする。
  多数の要求queue・arm/cancel・検出器・Qt操作・実入力schedulerは次の単位に分ける。

## 検証範囲

保存4/8ch f32/f64の元bytesと2bindingを実queueへ通し、32完全resultの全配列・来歴を独立oracleへ比較する。
遅い読者/分数trigger/追加FFT一回/通常平均不変、保持超過、旧世代、stop後の所有権を検査する。
pending/gapや未校正を正常数値に変えた証拠、偽ID・世代・position・残差・共有・解放記録を拒否する。
[再実行手順](../../native/trigger-capture.md)へsource/観測/hash/logの境界を記録する。

通常表示との回帰は既存両Qtの保存入力で確認する。trigger UIの成功として数えない。
callbackの新処理、実音声trigger・外部clock・性能/長時間・他OS・採用判断は今回の合格条件に加えない。

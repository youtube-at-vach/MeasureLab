# MIG-006-E 非同期snapshot保存の評価境界

2026-10-02。[決定0024](../migration/decisions/0024-async-snapshot-save.md)と
[MIG-008までの残工程](../migration/remaining-to-mig008.md)を参照。
既存の[実験用v1 JSON/CSV](result-candidate.md)を専用workerで保存する。
製品保存形式、Qtの保存操作、取得中の診断保存の置換はこの段階では含まない。

## 所有・完了・終了

[SaveWorker](graph-core/src/export.rs)をcontrol threadで作成し、
不変の `Arc<MeasurementResult>`、保存先、単一formatを `submit()` する。
受付では配列の複製、encode、ファイルI/Oを実行しない。mutexとmetadataのallocationがあり、callbackには使わない。
保存先は最大4096 bytes、receiptへコピーするresult IDは最大4096 bytes。
operation IDはworker内の単調番号で、別workerのreceiptを識別する共通IDではない。

容量は1〜8件で、待機中と書込み中の合計を数える。満杯は `Busy`、終了開始後は `Closed` で受付を拒否する。
cancel済みでもqueueから回収されるまで容量に数える。receiptを遅く読む利用者のために無制限の完了queueを持たない。
ticketはreceiptだけを保持し、完了・queue回収後の数値snapshotを保持しない。
job数の上限と、全snapshot・可変長metadata・CSV encoderのscratch・process RSSのbyte予算は別である。

`queued` → `writing` → `saved` / `failed` を実workerから通知する。
`saved` は全bytesの書込み、flush/sync、既存fileを置換しないpublishの完了後だけ。
保存失敗は元resultを変更せず、次の要求を処理できる。
現在のprofile/世代や表示間引きを参照せず、要求時の結果の全値・元精度・来歴を保存する。
過去の保持resultは取得の新世代になっても保存でき、receiptにも過去の世代/区間を残す。

`ticket.cancel()` は待機中だけ `true` を返す。書込み開始が先なら `false` で、実際の成否を通知する。
`close(Drain)` は新規受付を止めて残件を処理し、`close(CancelPending)` は未開始の要求をcancelする。
後者へ切り替えても書込み中の結果はcancelへ書き換えない。writer panicはpublish状態unknownのfailureとし、
新規受付を止め、未開始の要求をcancelして、joinでもfailureを返す。

`close()` はfilesystemの完了を待たない。`wait()`、`join()` と `Drop` は待つ可能性がある。
Qt接続時はjoin/Dropを専用の終了処理へ配送し、GUI threadやaudio callbackで実行しない。
進行中のOS書込みを安全に中断する仕組みや終了時間の上限は保証しない。

各fileは同じdirectoryの一時fileからhard linkでpublishし、既存fileを上書きしない。
filesystemのhard link対応が必要。JSON/CSVの組全体のtransaction、directory metadataのcrash durability、
別deviceへのpublish、製品の上書き操作は保証しない。

## 再検査

[Rust環境](README.md#このworktreeで使う)の `CARGO_HOME` / `RUSTUP_HOME` / PATHを設定する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core --lib export::tests
./.venv/bin/python scripts/migration_result_candidate.py --async-save --output .migration-local/async-save-new --report .migration-local/async-save-new/report.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_async_save_candidate.py tests/logic_verification/test_migration_result_candidate.py
```

出力directoryは新規にする。runnerは2校正契約/4交換例と4/8ch f32/f64の元fixtureを再検査し、
実graphの全相対/絶対配列を保存済み理論・現行値へ照合する。
その結果のJSON/CSVそれぞれをnative decoderへ通し、非同期保存、既存file拒否、親directory不在、
失敗後の復帰を12実行で検査する。36 savedと36 failedのreceipt、全resultの完全往復、元file不変、
snapshot回収、partial fileの残存がないことを確認する。期待配列や許容差を変更しない。
別環境の数値比較は明示的に `--portable` を追加する。

Rustではwriterを決定的に停止させ、容量、pending cancel、writingとの競合、Drain/Drop、panic、
過去profileの不変性、graphの進行と終了、snapshot回収を検査する。時間や性能の合格には数えない。
Native CIにNumPy-onlyの非同期保存比較を追加した。GitHubでの実行結果は別途確認する。

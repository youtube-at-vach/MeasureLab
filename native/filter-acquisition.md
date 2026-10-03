# Acquisition filter / rate integration

MIG-006-D-integration、2026-10-03。保存済みf64入力を実取得queueから一段filter、
worker所有履歴、共有FFTへ通す評価。採用判断と008-Aの全フロー統合は未完了。
[filterのpure境界](filter-candidate.md)、[決定0032](../migration/decisions/0032-acquisition-filter-scheduler.md)、
[進捗](../migration/status.md)を参照。

## 固定する構成

008-A向けの最初のfilter候補はf64、因果3-tap `[0.25, 0.5, 0.25]`、48→24 kHzの一段。
現行の保存fixtureと許容差を維持する。中心補償polyphaseの保存4 rate組合せと代表SOSも回帰対象にする。
f32を暗黙にf64へ変換しない。現在のCPAL/BlackHoleとQtの取得経路はf32/rawのままで、
今回のfilterは保存入力のf64 queueだけを検査する。実backendへのdtype選択とQt接続は後続。

1. `Acquisition<f64>`を作り、その実Sourceから`Filter::new`で親・出力Stream/Timebaseを固定する。
2. 出力Sourceと固定FFT仕様の正確なkeyへ、view/sessionのtokenを購読する。
3. 入力を消費する前に`Acquisition::attach_filter`へfilter、FFT仕様、専用履歴上限を渡す。
4. 同じ解析ownerの`poll`でraw blockをfilterへ配送する。
   `filtered_blocks`は元精度の全出力、`filtered_windows`は出力位置の履歴・FFT診断。
5. 保存入力の終了時だけproducerを停止し、queueをdrainして`finish_input`を呼ぶ。
   残る窓は`poll`でdrainする。`stop`/cancelは終端paddingを生成しない。

rawと派生FFTは同じgraph、別の履歴・位置を持つ。一段だけを接続し、両出力購読は一つのfilter stateと
同じFFT resultを共有する。各pollのframe配送は`frames_per_poll`、raw/派生の窓はそれぞれ
`windows_per_poll`以内。派生窓が上限に達したpollは新しいqueue配送を待つが、producerは待たない。
履歴が不足した窓は正確なmissing区間を返し、FFT数値を生成しない。
この境界はallocation/mutexを使う解析worker専用で、audio callbackやGUIから呼ばない。

FIR gapは次のraw blockか明示EOFでsupportへ拡張する。それまでは旧表示と平均を破棄し、
派生履歴に未取得の数値を置かない。SOSはgap・非有限・backend flags付き入力を明示failureとして
取得ownerごと終了し、queue/history/filter/tokenを回収する。SOSのzero-stateは全区間warmup。
容量failureも正常完了にしない。中心補償の先読みと末尾padding、信号遅延とunknown処理遅延を保持する。

親Trigger1024→派生512、信号遅延1/2 output sampleを有理数metadataで保持する。
写像されたeventの履歴queryも検査する。因果filterの遅延をTrigger位置へ黙って加減しない。
QtのTrigger操作と不変result作成は現状rawを使い、派生TriggerのQt配送/保存は未接続。

最後の出力token解除でgraphのfilterを回収し、次のowner pollで専用履歴を回収する。
raw購読は継続できる。親世代のrestartは派生の旧completionもfenceし、履歴を破棄する。
新世代にはtokenの明示reconfigureと新filterのattachが必要。外部の確定snapshotは不変。

## 検証と再実行

[native環境](README.md#このworktreeで使う)を設定し、リポジトリルートで実行する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core -p audio-core
./.venv/bin/python scripts/migration_filter_candidate.py --acquisition --report .migration-local/filter-acquisition-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_candidate.py tests/logic_verification/test_migration_audio_graph.py tests/logic_verification/test_migration_trigger_candidate.py
```

21ケース×5 callback chunk patternを実queue/取得schedulerへ通す。
callbackのwhole patternは8192 frame上限で分割する。pollは8192配送、raw/派生各1窓、
raw履歴256 frame、派生履歴512 frame。queueは8192 frame、gap例は128 frame。
gap `[100,104)`はその位置で132 frameをwriteして4 frameを実際にoverwriteする。
gap直後のcallbackだけはこの注入長を優先し、保持された128 frameは通常pollで取得する。
比較requestに期待値を渡さない。元入力の不変性、全出力/最終state、来歴、遅延、warmup/gap、
最初の有効共有complex FFTを独立した保存理論/現行値とNumPy FFTへ照合する。
chunk間の全出力bytes一致と、実取得frame数/欠落/各poll上限/寿命も要求する。

前後方向SOSと周波数応答は従来の完全配列adapterの回帰で、取得schedulerの因果経路と区別する。
6 rate境界は従来のpure契約検査。Rustでは2/4/8ch、EOF/cancel、SOS失敗、容量/履歴不足、
旧世代拒否、raw継続も検査する。reportの偽frame数/欠落/上限/寿命はPythonで拒否する。

比較前後のsource/runner/binary hashを照合し、途中で変わったreportは合格にしない。
別環境のNumPy-only検査は`--portable --acquisition`を明示する。
[Native CI](../.github/workflows/native-evaluation.yml)にも同じ実行を追加した。GitHubでの実行は未確認。
長時間/CPU/RSS/処理遅延、物理I/O/clock、f32、filter chain、SOS gap回復、全tap、
製品共通backend、Qt/保存接続は未確認。短い数値診断をAC15/16の性能合格にしない。

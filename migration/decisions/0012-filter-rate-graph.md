# 決定0012: graph所有のfilter/rate状態と保存比較

2026-09-30、MIG-006-D。着手時HEAD `a0d1bdb6`、`codex/migration-006-c`はremote一致・clean。
同じworktreeで`codex/migration-006-d`へ分岐。
[契約v0.1](../contracts/core.md)・[数値許容差](../contracts/numerics.md)・003-A/B/Cの保存参照は変更しない。

## 決定

[graph-coreのfilter](../../native/graph-core/src/filter.rs)を、一段のf64 worker transformとして追加する。
同じ出力Sourceの購読者はphase/stateを共有し、別係数/初期条件の同一性は区別する。
係数・rate・親Sourceを固定し、callごとに一括APIを再起動しない。

因果3-tap FIRと、現行の中心補償polyphaseは別の遅延条件を持つ。
後者は先読みを待ち、明示終端でのみ右端の0 paddingを使う。
warmup/gap/元validityをsupportへ伝播し、処理用の0を有効な測定へ変更しない。
信号遅延、補償、処理遅延を分け、rate写像とtrigger位置は有理数で保持する。

SOSは因果DF-IIと最終stateを保存参照へ比較する。
zero stateの過渡を理由なしに解除せず、全区間warmupを保持する。
IIR gap回復規則を今回新設せず、gap/無効入力はatomicに拒否する。
現行前後方向filterは完全配列の独立adapterで比較し、streamingの合格と分ける。

filter stateはgraphが所有し、最後の解除とshutdownで回収する。
親Streamのgeneration fenceは派生Stream、cache、購読snapshot、旧Completionの公開へ伝播する。
拒否前に新stateと派生fenceの容量を確認し、失敗時に旧stateを維持する。

JSON経由の保存係数で、既定parserが一部のf64を1 ULP変えることを開発比較で検出した。
既存のSerde JSON 1.0.151で`float_roundtrip`を有効にし、係数bitsまで厳密比較する。
新ライブラリの追加・Cargo lockの変更はない。

## 証拠と限界

[比較runner](../../scripts/migration_filter_candidate.py)と[手順](../../native/filter-candidate.md)で、
21保存ケース×5 chunk、6 rate境界、filter出力/履歴/共有FFTの所有権・validityを比較する。
元入力と保存係数だけを候補へ渡し、期待値はPython側に保持する。
manifestを丸ごと固定するNumPy-only readerは、環境一致以外をportable modeで緩めない。

開発中のRustテストの構文/variant名とbyte読み取りの型エラー、Clippyのchunk API指摘、
readerのJSON空白比較、テストで共有chunk辞書を変更した問題を修正した。
短いpolyphaseはpaddingで全FFT窓が無効になるため、FFT比較数を一律固定したテストも修正した。
最終比較と回帰は開発runから分け、結果を[status](../status.md)へ残す。

f32 filter、全rate/filter、IIR gap回復、chain、実取得/永続scheduler/Qt、
物理clock/処理遅延、release/長時間/他OSと製品品質の判断は未確認。
MIG-006-Dのpure境界と保存コーパスのAC10/14までで、MIG-006全体やRust/QML採用の完了ではない。
次は006-Eの不変result・channel校正・CSV/JSON来歴、または005の取得/graph接続へ進める。

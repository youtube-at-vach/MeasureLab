# Shared FFT graph candidate

MIG-006-B、2026-09-30。[コア契約v0.1](../migration/contracts/core.md#fft共有購読寿命)の
固定DAGを`graph-core`で検証する。Rust/QMLの採用、公開API、製品schedulerの確定ではない。
数値プリミティブには006-Aの`dsp-core`をそのまま使う。

## 入力・共有・所有権

固定経路はowned SignalBlock → FFT → 購読別のPSD平均と最新snapshot。
汎用graph editor、取得buffer、trigger/history、音声backend、Qt adapterは含めない。
入力は制御側で検証したframe-majorのf32/f64と順序付きChannelId。
Timebaseには有理数のrate/nominal rate、原点、clock domain、revision、generationを残す。
未知の原点時刻・不確かさは`None`のまま保持する。

FFT keyはSource全体（Stream/generation、ChannelId順、precision、Timebase全体、route/tap、
前段filter/state・校正revision）とN/hop/alignment、窓、DC除去、channel別input gainを構造で比較する。
hash衝突時も全体の等値比較を使う。窓はboxcar/symmetric Hannだけで、係数と対称性はenumで一意。
transform/正規化は`realfft-3.5.0-x-over-n-v1`、validity方針は無効窓全体の拒否に固定する。
任意の窓係数、periodic Hann、別transform版・別validity方針を同じkeyへ省略して受け入れない。
対象区間はkeyとstartの組で識別し、resultには半開区間・Source・条件を不変に保存する。

同じnodeの全購読は一つの`Arc<FftResult>`と同じgraph namespace付きresult IDを参照する。
購読ごとの色/表示単位はmetadataだけで、表示変換・QML描画は後続。
累積PSD平均はraw FFTの後段で購読ごとに持ち、開始・reset・世代/条件変更・測定gapで分離する。
input gainは有限の無次元補正だけを実際に適用する。V/SPL校正と保存は006-E。
公開後のresult/snapshotには共有可変データへの経路がない。
[標準ライブラリのArc/Weakの所有権](https://doc.rust-lang.org/std/sync/struct.Arc.html)を使い、
購読はGraphへのWeak参照を持つ非Cloneのtoken。Dropが購読を一度だけ解除する。

## 実行・停止・容量

`Graph::schedule()`は完全な窓のowned入力に対し、必要なnodeだけの`Job`を予約する。
frame数がN以上で、startがalignment/hopに合うnodeだけを対象とし、先頭N frameを使う。
履歴からの窓切出しは006-C。異なるNのnodeは必要なら別に計算する。
同一nodeのstartは単調増加。重複/逆順、nodeの処理中、容量超過は要求全体を拒否し、
一部だけ予約したり、黙って入力を捨てたりしない。予約したJobのcancel/dropはその窓を取り消す。

呼出し側の解析workerが`Job::compute()`を実行し、`Completion::publish()`で結果を公開する。
FFT中はgraph mutexを保持しない。Job/CompletionはSendで、Dropでもin-flight予約を回収する。
最終解除はnode/cacheを制御側で外す。計算中のowned入力・resultはJob/Completionが保持する。
公開時にnodeのincarnationと需要を再確認し、最後の解除後に同じkeyを再購読した場合も
旧Jobで新nodeを復活させない。条件変更後のviewへ旧世代の結果を適用しない。
Graphのshutdown/Dropは冪等で購読/node/cacheを解除する。外部で確保したJobを勝手に解放しない。
`wait_idle(timeout)`はJob/Completionの終了・Dropを待つだけで、workerの実行・joinの代替ではない。
file harnessはcaller-owned解析threadをjoinしてから停止とin-flight数0を確認する。
永続worker、取得queue、排他/再接続、実backend回収は005-A/Bと統合時の範囲。

上限はnode数、購読数、in-flight数、N/channel数、cacheの結果数とnumeric bytes。
cacheはLRU順、未保持結果を先に外し、全部が保持中ならgraphの参照だけを外す。
保持中のresultを変更せず、graph内のcache容量は常に上限内にする。
このbyte数は配列のpayloadであり、metadata/allocator overheadやprocess RSSではない。
購読別mailboxは最新snapshot一つだけ。置換数を数えるが取得gapに変換しない。
平均は通知の省略前に全公開結果へ適用する。遅い表示のreadを待って計算を止めない。
外部購読者が取り出して保持するsnapshotと、caller-owned Jobの寿命/メモリは呼出し側の責任。

すべて制御/解析worker API。alloc、lock、FFT plan生成、解放を含み音声callbackへ転用しない。
現段階はJobごとにAnalyzerを作る。plan再利用や定常性能の合格は主張しない。
無効spanはreason/位置/channelを残して数値を返さず、非有限入力/結果も`nonfinite`として返す。
0や前回の正常値への置換はしない。

## 再実行と判定範囲

[native環境](README.md#このworktreeで使う)を設定する。Qt SDKと実機は不要。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core --all-targets -- -D warnings
./.venv/bin/python scripts/migration_graph_candidate.py --report .migration-local/graph-verify.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_graph_candidate.py
```

通常runnerは保存fixtureを書き換えない。portable環境は`--portable`を明示し、hashと数値条件は維持する。
小規模14件と4/8ch 4件の元の`input.bin`をRustへ渡し、schema/hash/shape/ID順/Sourceと結果回収を確認。
元の入力hashを前後比較し、保存済み理論/現行値へFFT/単位/PSD/RMS/inverseを照合する。
003-AにないStream/Timebase IDは`graph-fixture.<case ID>`の仮想namespaceへ明示的に写像する。
原点時刻は推定で補わず、元metadataと写像後requestを両方reportへ保存する。

詳細reportとコマンドの圧縮log/hashは`.migration-local/`に置く。Gitには
[決定0008](../migration/decisions/0008-shared-fft-graph.md)と[進捗](../migration/status.md)へ条件・結果・限界を要約する。
純粋graphでAC05/06とAC07のnode/cache/in-flight寿命を検証する。
Qt画面・実取得/音声worker・実保存sessionとの統合、trigger/history、全体終了は後続。
拡張6件、release、steady-state、10分連続、描画性能、他OSは今回の検証範囲に含めない。

# Filter / rate candidate

MIG-006-D、2026-09-30。`graph-core::filter`はf64の解析worker用候補。
Rust/QML、製品resampler、公開APIの採用は未決定。
[保存参照](../migration/fixtures/filter-v1.md)・[決定0012](../migration/decisions/0012-filter-rate-graph.md)を参照する。

## 境界

- `Filter::new`で入力Source、独立した出力Stream/Timebase、保存係数、rateと初期条件を固定する。
  `output_source`へFFTを購読してから`Graph::attach_filter`で登録する。
- `Graph::process_filter`は絶対sample位置を保持する。入力chunkの大きさでphase/stateを再初期化しない。
  同じ出力の購読者は一つのfilter stateとFFT nodeを共有する。
- 因果3-tap FIRは`Σ h[j] x[2m-j]`。中心補償polyphaseは
  `up × Σ x[n] h[m×down + half - n×up]`。後者は必要な先読みまで出力を待つ。
  `finish_filter(end)`だけが終端を通知し、末尾のmissingや端点paddingを明示する。
  FIR tailを追加して延長せず、総出力はceil(N×up/down)。
- 負位置と中心補償の終端paddingは`warmup`、取得欠落は`gap`。
  FIRはreason/channel/originをsupportへ拡張し、nonfiniteの計算用0にも無効性を保持する。
  無効窓はFFT数値を公開せず、購読別の平均をresetする。
- SOSは保存係数のDF-II stateを保持する。zero-state過渡は全区間`warmup`とし、
  任意の経過時間で有効扱いにしない。gap/非有限入力/validity付き入力は、状態を進める前に明示拒否する。
  回復規則は未定義。前後方向SOSはodd padding/定常初期stateの完全配列adapterで、chunkごとに呼ばない。
- metadataは親Source/世代、rate比、原点写像、補償前の信号遅延、補償済みフラグを保持する。
  trigger1024→512、信号遅延1/2 output sampleを丸めない。
  SOSの周波数依存の信号遅延と未測定の処理遅延はnull。unknown origin/uncertaintyも維持する。
- 係数bits、因果/中心補償、比、revision、親のfilter stateを出力Sourceの同一性へ含める。
  JSONの係数変換はSerde JSONの`float_roundtrip`を使う。
- 一段のworker transformだけを登録する。重複出力Streamとfilterの連鎖を拒否する。
  最後の購読解除/shutdownでstateを回収し、親世代のfenceは派生Sourceと旧Completionへ伝播する。
  外部が保持する確定snapshotは不変。容量超過・不正入力の拒否はstateを変更しない。

既定上限は32ch、4097 FIR係数、16 SOS section、65536入力frame（今回callのgap込み）、
131072出力frame/call、4096 validity span。FIRの内部履歴は有限supportに必要なframeだけを保持する。
一時出力/validityも検査するが、metadata/allocator/外部snapshot/全process RSSの予算とは別。
allocationとgraph mutexを使うので、音声callbackから呼ばない。
保存f64の実取得queue/固定scheduler接続は[006-D-integration](filter-acquisition.md)へ追加した。
汎用scheduler、filter chain、実backend/Qtへの接続、f32 filter、品質/性能の採用判断は後続。

## 保存比較

導入済みのツールを[native環境手順](README.md#このworktreeで使う)で有効にする。
通常比較は元の入力bytesと保存係数だけをRustへ渡す。期待値をrequestに含めない。
manifest全体のhash、参照source/generator/契約hash、全133ファイルのschema/bytesを検査する。
fixture/許容差は更新しない。reportはfixture外の新しいファイルに保存する。

```bash
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
./.venv/bin/python scripts/migration_filter_candidate.py --report .migration-local/006-d-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_filter_candidate.py
```

FIR5、polyphase12、SOS4の21ケースをwhole/1/127/256/不規則chunkで比較する。
SOSの因果出力/最終stateと前後処理/複素応答を、保存済み理論と現行へ別比較する。
出力/最終stateはchunk間で同じbytes。6 rate境界は新契約の拒否とidentityを照合する。
filter出力→worker所有履歴→共有FFTへ64-frame窓を渡し、同一ID/allocation、validity、
平均reset、数値評価count、解除/shutdownでの回収を検査する。
有効窓があるケースは最初の共有complex FFTを保存理論出力の独立NumPy FFTへ照合する。
全区間warmupのSOSや短いpolyphaseの無効窓で、有効FFTを捏造しない。

最小依存環境/他OSは明示portable modeを使う。環境一致だけを省略し、source/係数/数値許容差を緩めない。

```bash
./.venv/bin/python scripts/migration_filter_candidate.py --portable --report .migration-local/006-d-portable-new.json
```

独立Rust CIへbuild/Clippy/NumPy-only比較を追加済み。GitHubでの実行結果は未確認。
最終結果と残る範囲は[status](../migration/status.md)へ記録する。

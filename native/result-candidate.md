# 不変result・校正・保存候補の再検査

MIG-006-E、2026-10-01。[決定0013](../migration/decisions/0013-result-calibration-exchange.md)を参照。
製品ファイル形式の確定はMIG-008で行う。この交換形式は検証用である。

## 実行

[準備手順](README.md)のRust環境を設定する。runnerはworktree内のtoolchainを優先し、
locked/offlineで`graph-core`の`result-candidate`だけをbuildする。
GUI、音声device、SciPy、FFTWをimportせず、既存の入力・期待値を変更しない。

```bash
./.venv/bin/python scripts/migration_result_candidate.py --report .migration-local/006-e-new.json
./.venv/bin/pytest -q tests/logic_verification/test_migration_result_candidate.py
cargo +1.98.1 test --offline --locked --manifest-path native/Cargo.toml -p graph-core
cargo +1.98.1 clippy --offline --locked --manifest-path native/Cargo.toml -p graph-core --all-targets -- -D warnings
cargo +1.98.1 fmt --manifest-path native/Cargo.toml --all --check
```

NumPy-only/他環境の比較には明示`--portable`を使う。環境版以外のmanifest、source/generator、
契約、全保存ファイルのhash、数値許容差の条件は変わらない。
Pytestの共通conftestはQt/audioをimportするため、runnerのheadless検査は独立processで実行する。

## 比較する範囲

- 003-Bの校正2契約と4保存例を、ChannelId順序、係数、revision、binding、区間、軸、
  trigger、Timebase、未知時刻、FS/V/dBV/SPLのvalidityまで比較する。
- 4/8ch × f32/f64の元`input.bin`を一つの共有FFTへ渡し、2viewと保存sessionで同じallocationを受ける。
  view解除後もsessionの需要を保持し、最後の解除/shutdownでnode/cache/in-flightを回収する。
- 保存結果はraw FFTの全配列をコピーし、表示間引きや独立平均で置き換えない。
  complexはreal/imag最終軸、f32 inverseはf64 JSON数値から元のf32 bitsを復元できる値を保持する。
- RMSのV/FS、dBV、PSDのV²/補正Hzを検査する。PSDの絶対密度は周波数補正のJacobianで割る。
  raw PSDはnominal Hz、絶対PSDはcorrected Hzに対応する。SPLはこの段階では全てuncalibrated。
- 各resultをJSON/CSVへ保存し、native readerと独立Python CSV readerで完全一致の再読込を確認する。
  profile/世代変更、停止、元graphの回収後にも確定結果は不変。

## 交換形式と失敗

JSONの`schema_version: 1`とCSVの`# MIG-006-E exchange v1`は実験用の版である。
CSVは最初のrowにJSON metadata（source、capture、軸、校正、列の単位/shape/precision）を持ち、
後続rowを`metric,index,value,reason`とする。nullは空欄と理由にする。
引用符、comma、Unicode、embedded newlineを引用したCSVで往復する。
未対応の版、未知field、重複JSON key、壊れたshape/単位/精度、null/reason不整合、
非有限数、未知channel、期限切れ校正区間、矛盾する世代/trigger/clock写像を拒否する。

校正はChannelIdに結び付けたsnapshotを`after_analysis`で適用する。
校正済みV/FSは`input.raw`だけに許可する。mixed tapや既に校正済みのtapへの単純な再適用を拒否する。
未設定/未校正の係数を絶対値の証拠にしない。zero RMSのdBVは`nonpositive`、非有限/overflowは`nonfinite`。
原点、acquired host時刻、trigger詳細、clock写像、不確かさのunknownを推定/zeroで補わない。

`save_new`は同じdirectoryの一時fileに`write_all`/flush/fsyncを完了してからhard-linkで公開する。
既存destinationは置換せず、途中失敗は成功を返さない。一時fileをcleanupする。
結果ごとの公開はatomicで、JSONとCSVを一組としてcommitする保証ではない。
filesystemのhard-link対応が必要で、directory metadataの電源断耐性は未検証。
writerのWriteZero/書込み/flush失敗と、directory不存在/既存file/不正destinationをテストする。

numeric payloadは結果あたり4,000,000 scalar、channelは32、validity spanは4096、読取fileは256 MiBを上限とする。
FFTの全配列をコピーする前に保守的な容量検査を行う。metadata/allocator、外部snapshot、全process RSSの上限ではない。
大きいFFTのsnapshotはこの初期上限を超える場合、明示拒否する。

003-Bの旧交換形への照合adapterは観測値を並替えるだけで再計算しない。
typed f64の係数`1.0`とcorrection`1.0`だけは旧fixtureの整数`1`という表記へ正確に戻す。
現行製品のCSV/JSON importer互換や旧設定の自動移行の合格を意味しない。

[セッションID校正の取得/Qt接続](calibration-display.md)を007-Aへ追加した。
Qtのprofile編集/適用、永続scheduler、非同期保存worker/cancel、SPL/周波数・位相map、実device校正、
legacy製品importer、長時間/性能/他OSは後続。AC12はpure校正/保存境界までの合格とする。

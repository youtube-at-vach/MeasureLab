# 0008: Pure shared FFT graph candidate

日付: 2026-09-30。状態: 検証済み候補、技術採用は未決定。
対象: MIG-006-B、AC05/06とAC07のgraph所有権部分。
開始: `codex/migration-006-a`の`4c6ea93e`から、同じclean worktreeで`codex/migration-006-b`へ分岐。
既存006-Aはcommit済みで、statusの「未コミット」は作業時の古い記録だった。

## 選択と境界

利用可能なIntel hostで完結する006-Bを先に進めた。005-Aの音声backend比較は独立して未着手。
`graph-core`を非Qtの独立クレートとして追加し、既存`dsp-core`を変更せず共有計算に利用する。
固定DAGはowned入力 → FFT → 購読別平均/最新snapshot。keyを構造で比較し、
resultの同一IDと同一allocationで計算共有を判定する。plan共有だけを合格にしない。
新しい外部ライブラリは追加せず、既存のserde/serde_jsonを同じ版で使う。

keyはSource（Stream/generation、ChannelId順、precision、Timebase全体、route/tap、
前段filter/state・校正revision）とN/hop/alignment、窓、DC除去、全input gainを含む。
窓・transform版・validity方針はサポートする一つの意味に固定し、未対応条件を暗黙省略しない。
表示条件は後段。平均は購読ごとの累積PSDで、開始位置・reset・gap/条件変更を独立にする。
未校正のFS相対値は参照できる。input gainは無次元補正だけで、V/SPLや保存は006-E。

Graph ownerはregistry/cache、nonClone tokenはWeakで購読を保持する。
Job/Completionが計算中の入力/結果を保持し、公開時に需要とnode incarnationを再確認する。
解除後の同じkey再購読、旧世代、shutdownでも古い結果で新nodeを更新しない。
公開済みresultは外部snapshotが保持でき、最後の所有者の解除まで内容は変わらない。

解析Jobは呼出し側のworkerが実行する。FFT中はgraph lockを保持しない。
永続scheduler・取得queue・callbackは実装しない。file harnessでは実threadを起動してjoinする。
これは実音声worker回収の合格ではない。全APIはalloc/lockを含みcallbackへ転用しない。
詳しいAPI・容量・停止の意味は[実行手順](../../native/shared-graph.md)へ置いた。

## 検証と結果

- Rust16テスト: 2/4/8chのf32/f64で単独購読と数値一致、2購読の同一allocation/ID、
  key条件ごとの分岐、表示だけの共有、独立平均、購読遅延、2view+sessionの最後の解除。
- 66区間をGUI相当のslow consumerが読まなくても処理し、FFT評価66、平均の参照数66。
  latest mailboxの通知省略を測定gapへ変換しない。取得gap相当の区間飛びでは平均をreset。
- 最後の解除・同key再購読・世代変更・shutdown/drop・Job cancel・cache容量超過を検証。
  未公開のin-flight結果と公開済みsnapshotの寿命をWeakで確認し、解放後に復活しない。
- 18保存ケース（003-Aの14件、003-Bの4/8ch 4件）で元input bytesを解析threadへ渡した。
  全件でFFT評価1、2購読が同じresult IDとallocationを保持し、保存済み理論/現行数値へ合格。
  解除/shutdown後のnode/subscription/cache/in-flightは全件0。入力hashは前後で一致。
  最大正規化complex FFT差はf64約5.99e-14、f32約8.35e-9。許容差の変更なし。
- NumPy 2.2.6とpipだけの既存最小venvでもportable比較18件成功。Qt/FFTW/音声依存なし。
- 独立Rust CIのpure jobへgraph test/build/Clippyとportable比較を追加。GitHub実行は未確認。

詳細reportはローカルの`.migration-local/2026-09-30-006-b-graph-final.json`、
`2026-09-30-006-b-minimal.json`、`2026-09-30-006-b-rust-checks.json`に保存。
ソース/lock/実行物/入力/outputのhashと、コマンドのgzip log/hash/終了コードを保持する。
最終数値・最小環境・Rust checkの41コマンドと現source/runner/実行物hashの整合を確認した。
判定条件、fixture、許容差、現行DSP/UIは変更していない。

初回Rust test/Clippyと数値比較は成功。最終Ruffは新テストのS603を検出し、
ローカルbuildした既知binary・明示argv・shellなしである理由を該当行へ明記して再検査した。
時間は短いfile比較の診断値で、速度比、定常性能、AC15/16の合格に使わない。

## 残る検証

AC05/06とAC07のpure graph/node/cache/in-flight境界までを006-Bの成果とする。
QML adapter/画面再生成、永続worker/実取得、実保存session/ファイル書込みとの統合は未確認。
trigger/history/Timebase写像は006-C、filterは006-D、校正/保存は006-E。
キャッシュ制限はgraph所有のnumeric payloadだけで、外部に保持するsnapshotや全process RSSは別。
入力queueは作らず、busy/容量超過を明示拒否する。取得queueのgapは005-A/006-Cで扱う。
JobごとにAnalyzerを作り、plan再利用、CPU/RSS、10分連続、拡張6件、release、他OSは未評価。
Rust/QML採用、公開API、P2フロー全体、41機能の移行完了を決定しない。

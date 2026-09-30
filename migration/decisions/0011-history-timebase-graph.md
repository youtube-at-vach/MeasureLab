# 0011: Worker-owned history and Timebase integration

日付: 2026-09-30。状態: 検証済み候補、Rust/QML採用は未決定。
対象: MIG-006-C、AC08/09のpure履歴/Timebase/世代/共有graph境界。
開始: `codex/migration-005-virtual`の`f9ff4558`から、同じclean worktreeで`codex/migration-006-c`へ分岐。
005-virtualはremote一致・commit済み。statusの「未コミット」は前回作業時の記録だった。

## 選択と境界

利用可能なhostだけで完結する006-Cを進める。BlackHoleの回帰経路は維持し、deviceを開かず
003-Bの保存例と元の4/8ch入力で検証する。外部ライブラリ、Cargo lock、契約、fixtureを変更しない。
既存`graph-core`へhistory/time moduleと独立したfile harnessを加えた。
履歴は解析worker側でowned chunkを保持し、通知が遅れても絶対位置で非消費queryする。
reader cursor、snapshot寿命、retention上限を分離する。音声callbackのqueueとは別のAPI。
block条件を保存し、route/filter/校正revisionが異なる窓の混合は明示拒否する。

restartは新構成の検証、graph公開の世代fence、履歴の交換という順序で行う。
旧in-flight結果は寿命を保って解放し、公開済みの外部snapshotは不変。
gap/pendingはFFTへ入れず、既存validity spanは理由・範囲・channelを保ってgraphへ渡す。
fenceは購読上限数までで、boundedな検証候補とする。
time写像は有理数で確認し、未知原点・同期・不確かさを推定で埋めない。
詳しいAPI/制限は[再検査手順](../../native/history-candidate.md)に置く。

## 検証

- 保存契約13件（履歴9/時刻4）に完全一致。`[1792,2816)`、retentionの`[1792,1904)`、
  gap `[100,104)`、future pending、負位置、floor/残差、旧世代と別Timebase拒否を確認。
- 保存4/8ch × f32/f64の4入力を不規則chunkから復元。二つのreader、遅い通知、retention後の
  owned snapshotの全bytesが元入力と一致。FFTは保存済み理論/現行値の許容差内。
  一つのFFTと同じresult ID/allocation、終了後のnode/subscription/cache/in-flight数0。
- graph Rust27テストのうち006-C追加11件。世代変更前に計算済みのCompletionの公開拒否、
  cache/mailbox/平均の解除、failed restartの原子性、validity/gap、未知clock/写像期限を検査。
  4/8chと両精度の断続取得を独立したframe集合oracleと照合し、retention内の位置/値を確認。
- Pythonの候補境界27テスト。契約の位置/reason/型、metadata/ID/共有/回収数、
  元bytes/FFT破損を検出。期待値を含むrequestを拒否し、既存output/入力を保護する。
- 独立Rust CIのpure jobへharness buildとNumPy-only portable比較を追加。GitHub実行は未確認。

開発時にharnessの所有権のコンパイルエラー2件とClippyの`manual_pop_if`1件を修正した。
最終runと開発runを分けてローカル`.migration-local/`へ保存する。
report・コマンド・最終検証の実行結果は[status](../status.md)を参照。

## 残る範囲

006-Cはsynthetic取得からpure共有graphまで。005-A queue/実backend/永続worker/Qtとの接続、
実clock推定/物理遅延/外部trigger、保存MeasurementResult、steady-state/他OSは未確認。
numeric上限は保持payloadだけで、metadata/allocator/外部snapshot/全RSSを含まない。
route revision境界をまたぐ窓の分割/汎用処理は後続で決める。
006-Dのfilter/rateと006-Eの校正/保存へ進める。採用や41機能の移行完了を決定しない。

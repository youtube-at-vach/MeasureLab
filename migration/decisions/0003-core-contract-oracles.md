# 0003: 仮想多ch参照と新契約のoracleを分離する

日付: 2026-09-30。対象: MIG-003-B、[コア契約v0.1](../contracts/core.md)。
契約・数値許容差・技術採用の変更はない。

## 判断

現行FFTManagerの1ch演算を4/8本へ適用する参照と、現行AudioEngineにない能力の期待値を分ける。
後者は[手計算ケース](../../scripts/migration_core_cases.py)と
[契約モデル](../../scripts/migration_core_oracle.py)で照合し、由来を`new-contract-oracle`と明記する。
Pythonによる別計算だけで候補コアのAC合格や現行engineの多ch対応を主張しない。

## 境界

- FFTは003-Aの現行関数・独立解析式・厳密なsource固定を再利用する。既存003-Aのscriptやfixtureは変更しない。
  AC01の4/8chをf64/f32で保存し、IDごとのbin・peak・RMS・phaseと全complex配列を照合する。
- routeの行列、入力配列順、出力数、非zero寄与channel、reasonの和集合を固定する。
  FSでのmixに、異なるV/FSを持つ入力を代表する一つの校正係数を捏造しない。
  このfixtureの`single_v_per_fs: null`は合成校正を行わないことを表す。
- route要求は入力で宣言した次のblock境界に適用する。ackには実適用sampleを返す。
  queue競合や複数保留要求の置換方針は定義・実装しない。
- 履歴モデルは取得済み区間・high watermark・容量から、snapshot/pending/gapと正確な区間を返す。
  各読者の要求は独立。ownedなmetadataコピーは検査するが、波形の実保管・pool・cursor管理の実装ではない。
  MIG-006-Cで同じfixtureと実データのsnapshot保持を合わせて検証する。
- 保持期限切れと取得欠落はどちらも`missing`と正確な区間を返す。未来のpending区間とは分ける。
  gapとpendingが同居する応答では両方を保存し、取得済み部分に欠落があるため全体statusはgapとする。
- 同一Timebaseの原点からの時刻は有理数、clock間写像は有効区間と世代付きで検証する。
  原点の不確かさunknownを0と同一視しない。
- tapの量子化例はstep=0.25、ties-to-even、ditherなしの決定的な仮想例。
  製品量子化器や旧loopbackの実行結果ではなく、mute後のdevice bufferとmixedを区別するための条件である。
- 校正・単位・軸・Timebase・trigger/route/tap・validityをJSONとCSVへ保存して再読込する。
  CSVは共通metadataのJSON行とchannelごとの数値/校正/reason列を持つfixture専用形式。
  製品exporterの互換adapterや製品保存schemaの採用ではない。

## 固定と検査

[runner](../../scripts/migration_core_reference.py)は入力・手計算期待値・配列・保存例のhashを保存する。
契約文書、runner、003-Aのsource/依存版も固定。metadata・整数位置・有理数・reasonは厳密一致、
数値だけを既存の許容差で照合する。通常verifyは期待値を更新しない。
再生成は新しいディレクトリに限定し、保存manifestと全82ファイルのbytes一致を確認した。

未実装の候補core、共有graph、物理I/O、既存CSV/JSONとの互換、性能・他OSは後続タスクに残る。
MIG-003全体は003-Cのfilter/rate fixtureが揃うまで完了としない。

# 0036: Fixed filter outputs in both Qt adapters

日付: 2026-10-03。対象: MIG-006-D-filter-Qt。採用判断ではなくP2の検査単位。

## 判断

前段の[既存の検証結果](../status.md#再利用する証拠)を同じ解析ownerへ接続し、
両Qtの購読を一段filterの派生FFT keyへ切り替える。
因果3-tap `[0.25,0.5,0.25]`、48→24 kHzを固定し、requestで明示選択する。
raw経路とdevice実精度を保持し、汎用filter UI・f32演算・chainはこの単位に含めない。

Triggerは派生履歴へ非消費queryを行い、派生domainのeventと窓長を要求する。
親eventの自動写像と信号遅延補償は行わず、間違ったStream/世代を拒否する。
共有raw FFT cacheを再利用し、通常viewのmailboxや平均を巻き戻さない。

親/出力Sourceと変換・rate/遅延metadataを不変resultの`conditions.filter`へ保持する。
既存v1/製品codecへ同じsnapshotを渡し、4形式の配列・来歴の往復を検査する。
既存raw snapshotのschema/内容は維持する。codec読込み時にも来歴の整合性を検査する。

## 根拠と制限

検証結果・途中の失敗・保存先は[進捗](../status.md)、再実行は
[filter/Qt手順](../../native/filter-qt.md)へ記録する。
元fixture/係数/許容差と製品DSP/GUIは変更しない。
独立有限和、共有FFT/Trigger、pin/save、世代/回収と短いBlackHole診断を対象にする。
全tap/動的route、永続profile、長時間性能/他OSと008-A全体は完了にしない。

派生rateでの軸初期化と、親/派生の異なる窓長に対するreplay drainを修正した。
Hannの検査で既存Trigger oracleのtone RMS端点処理の誤りを検出した。
DCと偶数NのNyquistはpeakとRMSが一致し、内部binと奇数Nの最終binはpeak/√2となる。
既存DSPと数値契約へ合わせ、独立した時間領域RMSの証明testを追加した。
元fixture、FIR/FFTの許容差とDSP演算を変更していない。失敗reportを保持し、成功件数から除外する。

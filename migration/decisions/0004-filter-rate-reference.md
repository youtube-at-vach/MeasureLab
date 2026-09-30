# 決定0004: 最小FIRと現行filter/rate参照の境界

2026-09-30、MIG-003-C。[数値契約v0.1](../contracts/numerics.md)は変更しない。
Rust/QMLや製品resamplerの採用を決める記録ではない。

## 背景

AC10にはchunkを跨ぐ因果FIRの位相・gap・時刻が必要。
一方、現行`AudioCalc.resample`は一括polyphase、`lowpass_filter`は前後方向処理で、
状態を渡すstreaming APIではない。この三者を同じ意味の出力として扱わない。

## 決定

- 最小3-tap FIRは新契約モデルと呼ぶ。絶対位置で欠落を表し、有限和・手計算例・別のconvolution検査で照合する。
- 現行polyphaseは関数を直接実行する。係数・padding・補償を固定し、独立sinc/Kaiser式と有限和を別保存する。
- 代表SOSは8次Butterworth 4 kHz lowpassに限定し、現行の前後処理と独立direct form Iを比較する。
  因果処理は同じ係数のSciPy参照として由来を明記し、zero stateからのchunk一致と最終stateを検査する。
- 時刻写像・信号遅延は厳密な有理数。未測定の処理遅延はnull/reasonを保持する。
  無効なgap出力の計算用0を、有効なゼロ測定として扱わない。
- 現行のinvalid rate返却と、独立chunk呼出しの長さ/端点差を既知差として残す。製品コードは修正しない。
- 既存003-A/Bの参照を更新せず、別fixture v1へ全入力・期待値・係数・metadata・hashを保存する。
  verifyは書込まず、再生成は新しいディレクトリへの明示操作とする。

## 証拠と限界

[fixture仕様と結果](../fixtures/filter-v1.md)に要約と再実行手順を残す。
詳細reportはローカルの`../fixtures/runs/2026-09-30-intel-filter.json`に保持し、Git管理外に置く。
21件の数値ケースと6件のrate境界が契約内。chunk状態を保持するFIR/因果SOSは一致し、
一括APIを独立chunkごとに再起動すると差が出ることを確認した。

IIRのgap回復、FIRの末尾欠落に対する終端通知、世代切替、f32 filter、全rate/filter構成、
Rust実装・graph・物理I/Oはこの参照の対象外。性能の採用判断にも使用しない。
MIG-003の完了は、A/B/Cの保存参照と再現検査が揃った意味に限定する。
MIG-006-Dでは同じ保存入力を候補実装へ渡し、graph内のstate/phase/validityを追加検証する。

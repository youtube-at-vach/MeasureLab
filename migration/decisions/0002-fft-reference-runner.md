# 決定0002: MIG-003-Aの参照境界

2026-09-30、状態: 評価用runnerの実装方針。Rust/QML採用や製品FFT修正の判断ではない。
前提は[決定0001](0001-p0-contracts.md)と[数値契約](../contracts/numerics.md)。数値許容差の変更はない。

## 決定

- `9fd79958`の現行FFT/窓を直接呼び、入力bytes、理論と現行の結果、source/adapter hashを分離して保存する。
  source hashは基準commitのbytesから固定し、shallow checkoutでも基準との差を検出する。
- 理論FFTは有限幾何級数で計算し、別の小さい直接DFTと手計算例で検証する。
  peak/PSD/時間RMSの契約式はadapterと明記し、製品の表示関数を検証したとは扱わない。
- GUIファイル内の現行Spectrum計算は、対象メソッドASTだけを変更せず実行する明示adapterを使う。
  GUI/デバイスmoduleをimportしない。対象ファイル全体のhashが違えば停止し、adapterの再評価を要する。
  対象は矩形窓・平均なし・DC/Nyquist・ゼロ校正offsetだけ。旧表示の差を理論側へ取り込まない。
- 数値再現性用FFTは1 thread・FFTW_ESTIMATE・空wisdom。性能比較時には別途protocolの条件で測定する。
- 小規模14ケースの全配列をGitへ保存。非2冪/極大6ケースは全hash/生成式/結果を保存し、配列をローカルで保持する。
  再生成した拡張manifestはGitにあるbaselineと照合する。
- 通常検査と明示的な生成を別コマンドにする。生成は新規ディレクトリだけ。
  異なる環境の比較は明示的なportable modeとして記録し、厳密な環境再現と区別する。

## 結果と未確認

[fixtureと実行記録](../fixtures/README.md)に20ケースの理論照合、現行表示の差、再現コマンドを保存。
f64/f32、奇数終端、PSD積分、inverseの比較は成功。極大ケースの単発時間/RSSは性能採用判断に使わない。
4/8ch・route/trigger/history・校正metadataのoracleは003-B、filter/rateは003-C。
候補Rust実装、Qt接続、物理I/O、他OSでの実行、全UI/全体CIは未確認。

# 0017: BlackHole input.rawを共有result表示へ接続する

日付: 2026-10-01。MIG-007-Aの保存replay表示に続く実入力境界。技術採用の決定ではない。

## 判断

通常音声回帰をBlackHole 2ch／16chで進める既存指示に従い、USB操作や他OSを待たずに
CPAL callback→固定queue→履歴／共有FFT→不変result→両Qt表示を一つのフローへ接続する。
005の診断実行物と製品Python engineを維持し、input-only ownerを`audio-probe` libraryへ追加する。
`display-core`の`live-audio` featureから使い、pure検査はCPAL／ALSA依存なしで継続できる。
外部依存の固定版は変えず、Cargo.lockの変更はdisplay-coreから既存audio-probeへの依存1件だけ。

callbackは既存の固定容量取得queueとatomic counterを使う。
解析threadがstreamのopen/play/pause/drop、履歴、実graph購読、result作成と保存証拠を所有する。
保存replayと実入力で購読同期・raw allocation共有検査・GUI通知・回収検査を共通化する。
最新通知の置換は取得を止めず、QObject破棄は解析threadをjoinしてstreamも回収する。

exact device、device channel数、論理ID、物理port、f32／48 kHzを明示する。
不明なdeviceへのfallback、f64→f32暗黙変換、clock原点／不確かさの推定は行わない。
この短時間評価ではgap／callback失敗／3秒無入力をfailureにし、製品の回復方針とは分ける。

## 証拠と次の境界

[runner](../../scripts/migration_qt_live.py)はBlackHoleの2chと16chから選ぶ4ch／8chを両方式へ通す。
取得窓の元bytesと全FFTを独立NumPy計算へ照合し、既存f32契約を使う。
ポート別toneは別に検査し、stream回収・全需要解除・再生成・遅いGUI・世代fence・PNGも要求する。
詳細と再実行は[実入力表示手順](../../native/live-display.md)、実施結果は[status](../status.md)を正本とする。

最初のsmokeではrunnerがf32にf64相当の絶対閾値`2e-12`を当て、正しいf32丸め差を拒否した。
DSPは精度Tを維持する既存実装なので、runnerを既存f32契約へ修正した。契約の緩和ではない。
失敗runを保持し、修正後に新しいdirectoryで測定する。

trigger／保持履歴操作、基本校正／保存UI、9言語と分離windowを後続007-Aに残す。
全tap／製品共通adapterは005、長時間性能と編集反復は007-B、他OS／配布と採用比較は004／008で扱う。
BlackHole結果を物理device保証や007-A全体の完了に置き換えない。

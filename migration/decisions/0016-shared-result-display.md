# 0016: 保存取得resultを両Qt adapterで複数表示する

日付: 2026-10-01。MIG-007-Aの初期表示境界。Rust/QMLやQt adapterの採用決定ではない。

## 判断と実装

005の取得queue/履歴/共有FFTと006-Eの不変resultをQMLへ接続する。
004-A/Bの模擬worker・反復比較を保つため、`display-core`、`cxxqt-display`、`qtbridge-display`を分離する。
固定済み依存を再利用し、新規外部依存は増やさない。

workerが保存入力を繰り返し取得し、実graphでview/sessionの需要を管理する。
同一区間の全購読のraw allocationを確認してから、一度だけ不変resultと表示projectionを作る。
GUIへは容量1の通知mailboxを使い、解析を表示通知の消費から独立させる。
QObject破棄はstop/joinを行い、旧世代通知は新世代のpending bitとsnapshotを変更しない。

QML Canvasを最初の描画候補とし、同じprojectionをline/heatmapで読む。
全binの解析精度を保持し、描画は最大値で画素へ縮約する。cursorとworker保存は間引かない。
heatmapは最大32の表示snapshotをsample時間で配置する。未表示区間は空白、未知clockと未校正を明示する。
画像保存中に表示snapshotを保持するが、解析を止めない。

## 検証の範囲

[runner](../../scripts/migration_qt_display.py)は003-Bの4/8ch f32/f64の元bytesを両方式へ通す。
同じID/区間/Timebase、FFT allocation共有、cursor/zoom、cancel/失敗、遅いGUI、購読解除、
Backend/表示再生成、PNG、終了後worker/model回収を検査する。
各実行の3世代の完全なresultを保存し、全peak配列/軸を既存の理論と現行FFTへ照合する。
PNGは保存markerだけでなくCRC、寸法、line/heatmapの画素を検査し、目視も行う。
実施件数・誤差・command/hashの所在は[status](../status.md)を正本とする。

入力は保存replayであり、実音声デバイスのGUI統合ではない。workerは解析用で、callbackへ転用しない。
Canvas/software描画の性能評価、trigger UI、製品保存/校正UI、分離window、9言語、他OS/配布は残す。
英語のQML最小サイズと既存Python全言語サイズは検査するが、9言語QML完了には数えない。
007-A/007-B/008全体とRust/QML採用判断を完了にしない。

## 次の作業

005のBlackHole入力をこの表示所有境界へ接続し、trigger/保持履歴・基本校正・保存操作を同じフローで検査する。
表示言語と分離windowの要件を固めて007-Aを完了した後、007-Bの性能/反復protocolへ進める。
製品共通adapter/全tapは005の未完了項目として並行せず個別に再開できる。

# BlackHole実入力の共有result表示

MIG-007-AのCPAL input.raw→解析owner→共有result→両Qtの実装。
現在の範囲と次の作業は[MIG-008計画](../guide/RUST_QML_MIGRATION_PLAN.md)を参照。

## 代表条件の再実行

[native環境](README.md#このworktreeで使う)を設定し、関連コードを変更した場合だけ実行する。
既存BlackHole 2chを完全一致で指定する。48 kHz / 256 frames / f32。
system default deviceは変更しない。出力刺激はBlackHoleだけへ送る。

```bash
./.venv/bin/python scripts/migration_qt_live.py --virtual-device --qt-prefix .tools/qt/6.11.2/macos --case 2-to-2 --repeat 1 --output .migration-local/live-new
```

[runner](../scripts/migration_qt_live.py)は取得窓bytesと元値/port/bin/振幅、独立FFTと回収を検査する。
f32の既存許容差`atol=2e-6, rtol=2e-5`を維持。新しい出力先を指定する。
4/8chは統合coreの保存回帰に限定し、実deviceの全条件反復へ広げない。

## 所有権と停止

- [CPAL入力owner](audio-probe/src/live.rs)を解析threadで作成・開始・停止・破棄する。
  callbackは容量8192 frameのqueueとatomic counterのみを操作する。mutex・JSON・ファイルI/Oは使わない。
- [実入力scheduler](display-core/src/live.rs)が最大1024 frame／1窓を2 ms間隔でpollする。
  履歴は2N、入力はf32／48 kHz、FFTは最大4096 frame、論理chとdeviceは最大16ch。
  実graphの購読／raw allocation共有／不変result／容量1のGUI通知は保存replayと共通。
- 準備中cancel、二重開始／停止、最後の需要解除、再オープン、QObject再生成と動作中終了を検査する。
  GUIを320 ms止めても解析threadを動かし、古い通知を世代で拒否する。
- queue gap、callback失敗、3秒無入力を明示failureにする。短い正しさ検証の方針であり、
  製品のXRUN継続／USB復帰方針ではない。停止失敗も成功にしない。
- backend timestampからclock原点・不確かさを推定しない。両方null、電圧はnull＋uncalibratedのまま。
  stream破棄後の診断とgraphのnode/subscription/cache/in-flight回収を保存する。

## 手動表示

[実入力scheduler](display-core/src/live.rs)が読むrequestを
`MEASURELAB_DISPLAY_REQUEST`へ指定して`native/target/debug/cxxqt-display`を起動する。
requestのdevice/rate/ID/port/世代を明示する。[共通入力](audio-core/src/backend.rs)と
[Qt接続](display-core/src/lib.rs)が実装の入口。
長時間、別OS/物理遅延、全tap/製品設定の追加はMIG-008の前提にしない。

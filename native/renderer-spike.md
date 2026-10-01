# MIG-007-C Plot Renderer Feasibility Spike

現在の[簡易plotter](qml/SpectrumView.qml)を基準に、wgpu 30.0.1による最小compute rasterを1候補として試す。
rsplotは今回は試験していない。**採用判断・製品組込み・個別widgetの本実装は行わない。**
[計画](../guide/RUST_QML_MIGRATION_PLAN.md#121-mig-007-c-plot-renderer-feasibility-spike採用判断ではない)と
[進捗・結果](../migration/status.md)を参照。

## 境界と条件

- [Rust候補](renderer-spike/src/main.rs)と[WGSL](renderer-spike/src/plot.wgsl)は独立workspace/lockを持つ。既存native workspaceの依存版は変更しない。
- Spectrumはf32の10万点・100万点。同じ決定的な入力bytesと移動する1 binのpeakを使い、1024画素列へ最大値を縮約して描画する。
- Spectrogramは1024 bins×32行をGPU buffer上で循環させ、新しい1行だけをuploadする。RGBA画像は1024×256 pxで毎回全体を生成・読み戻す。
- 基準は既存のSpectrumViewをそのまま使う。[試験QML](renderer-spike/Spike.qml)が最小操作と購読用adapterを追加する。両方式のデータ領域を1024×256 pxに揃える。
- 目標更新30 Hz、warmup 3更新、Spectrum 30更新、Spectrogram 40更新、各3回。単独viewの短時間試験で、MIG-007-Bの10分統合性能検証ではない。
- 基準はNumPy→Python配列→JSON→QML→Canvas、候補はRust→wgpu→RGBA→IPC→PyQt image provider→QML Image。入力生成・転送・描画を含む経路全体の比較である。
- 画素・入力hash・元データcursorのoracleは候補の全更新を検査する。更新周期の測定後に実行し、時間を別記録する。CPU全run値にはoracle・warmup・生成/破棄も含む。

## QML接続とライフサイクル

[runner](../scripts/migration_plot_renderer.py)のPyQt hostがRust子processを所有し、
QQuickImageProviderへ所有するQImageを渡す。providerはQQmlApplicationEngineの寿命に従う。
Imageは毎更新で別のURLを使い、cacheを無効にする。この最小adapterはGUI threadで読み戻しを待つため、
非同期worker/mailboxへの置換とGUIの応答性は後続の確認事項である。

Zoom/Panは表示範囲だけを変更する。画面座標↔周波数の変換と、cursorが表示縮約前のf32値を参照することを検査する。
viewの破棄・再生成、GPU ownerのstop・再生成による履歴の初期化、
GPU更新要求直後のQML engine破棄と、その後のGPU完了・owner破棄を確認する。
GPUの未完了処理には10秒のpoll期限、比較子processには240秒の期限を設け、失敗logも保存する。

QtとのGPU texture共有、CXX-Qt/Qt Bridgeのnative接続、render threadの資源管理は未検証。
画像provider経路の成立を、それらの経路の合格に置き換えない。
APIの根拠は[Qt image provider](https://doc.qt.io/qt-6/qquickimageprovider.html)と
[wgpu bufferのmap/poll](https://wgpu.rs/doc/wgpu/struct.Buffer.html)。

## 負荷とコピーの記録

CPUはPython hostとRust子processのCPU秒と、生成/破棄・oracleを含むrun全体のCPU率を記録する。
RSSは各processのhigh-waterであり、同時点の合計や長時間の増加率ではない。
macOSでは250 ms間隔でIOAcceleratorのdevice使用率を読み、測定区間の中央値とraw値を保存する。
これは他アプリも含むGPU全体の値で、候補だけの負荷や0%時の無活動を保証しない。
GPU timestampが未対応ならpass時間はnullとする。未計測を0 msにしない。

| 経路 | 1更新当たりの明示的な操作・転送 |
| --- | --- |
| 候補の入力 | input upload 1回、uniform upload 1回。Spectrumは400,000/4,000,000 bytes、rolling imageは新規行4,096 bytes、uniformは32 bytes |
| 候補の画像 | GPU→readback bufferのcopy 1回、mapped buffer→Vecのcopy 1回、IPCで1,048,576 bytes、QImage.copy 1回 |
| 基準の入力 | NumPyの周波数/値の2配列をPython配列化し、JSON encode・QML decode。生成JSONのbytesを記録 |
| 内部処理 | OS pipe、Qt/driver内部のcopy回数、UMA上の物理転送回数は未確認。上記はコードで確認できる操作数 |

候補のrolling入力は部分更新だが、QMLへ渡す画像は全体読み戻しである。
GPU bufferへの入力upload、readback、CPU Vec/QImageのcopyとIPCが残る。
非同期転送・共有textureによる削減余地は後続の検証材料とする。

## 再実行

worktree専用のPython/PyQt Qt runtimeを使う。Qt開発SDKのframework/plugin/QMLパスを混在させない。
リポジトリのルートで実行する。

```bash
export CARGO_HOME="$PWD/.tools/cargo"
export RUSTUP_HOME="$PWD/.tools/rustup"
export CARGO_BUILD_JOBS=4
.tools/cargo/bin/cargo +1.98.1 build --release --locked --manifest-path native/renderer-spike/Cargo.toml
./.venv/bin/python scripts/migration_plot_renderer.py --output .migration-local/007-c-new --repeat 3
.tools/cargo/bin/cargo +1.98.1 test --locked --manifest-path native/renderer-spike/Cargo.toml
.tools/cargo/bin/cargo +1.98.1 clippy --locked --manifest-path native/renderer-spike/Cargo.toml --all-targets -- -D warnings
.tools/cargo/bin/cargo +1.98.1 fmt --manifest-path native/renderer-spike/Cargo.toml --check
./.venv/bin/pytest -q tests/logic_verification/test_migration_plot_renderer.py
```

出力先は新しいディレクトリにする。report、入力/source/lock/実行物のhash、command log、QML/GPU画像を保存する。
既定はQt offscreen/software/Basicで、候補のwgpu側は実adapterをreportする。
基準100万点の失敗も保持して残りの試験を継続し、失敗が1件でもあれば比較runnerは終了1を返す。
終了0やmarkerだけで合格にせず、画素/元データ/cursor/rolling history/表示再生成/終了の検査を要求する。

[独立CI](../.github/workflows/native-evaluation.yml)はRust build/test/Clippy/formatとPythonの不正証拠拒否を検査する。
CIにGPU実行・Qt性能測定を追加していない。GitHub実行、他OS、実音声、9言語QML、
複数view、長時間、校正・保存操作と製品互換は未確認。

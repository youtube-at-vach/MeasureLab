# グラフ近傍操作と表示切り替えの検証

2026-10-10。対象は `f80d36e9` を基にした `src/app.rs` の作業ツリー変更。macOS 14.8.9、Rust 1.99、Metal／AMD Radeon R9 M290X。段階3fの操作と表示切り替えに限る確認であり、Normal／Single・Autoset・結果読み戻しや長時間性能の検証ではない。

## 確認したこと

* `cargo fmt --all -- --check`、全ターゲット・全機能のClippy（警告をエラー扱い）、テスト、通常のreleaseデスクトップビルドが成功。テストは数値・ワーカー等120件、起動オプション1件と全ベンチターゲットを実行した。
* `--ui-smoke` の内部f64保持信号で通常幅1440×860の4表示、狭幅1040×780のScope＋Spectrum、Spectrum単独を撮影した。画像は2倍の物理ピクセル。操作は既存の見出しと表示切り替え行に収まり、数値・カーソルの位置とプロットのレイアウト計算は維持した。
* 狭幅でScopeのAdjust、SpectrumのDisplay／Analysisを開き、設定パネルを同時に開いた条件と非表示の条件を確認した。Scopeの時間軸・振幅・CH・トリガーと、Spectrumの解析設定・表示範囲・PSD帯域がメニュー内に収まる。PSDはCH 1の校正付きV²/Hzも確認した。画像・ログは `dist/controls-qa/` に置いた。
* devビルドの内部デモ・2ch・48 kHzで8秒のライフサイクルQAを実行した。Scopeが非表示でも生サンプルとX固定カーソルが進み、STFTの設定・世代を維持した。停止後に単独／2表示／全表示と元の表示選択・配置へ切り替え、書き出し対象のf64結果全体・取得条件・校正・解析区間・平均／保持・カーソルが同一であることを照合した。
* 同じQAで停止中の校正編集、再開、遅着結果除外、Spectrogram／XYの既存操作も成功した。取得／Spectrum入力の欠落と無効窓は0。releaseビルドと並行した短時間の状態遷移確認なので、CPU・応答時間の性能基準には使わない。
* 文書用PythonのRuff check／format check、全160件の文書のMarkdown lintとGitの空白チェックも成功した。

## 再実行

共通の検証コマンドは [Tool Usage Guide](../../../.agents/workflows/tool_usage.md) を参照する。UI用の環境変数は [README](../README.md#検証計測) に保持する。

```sh
MEASURELAB_UI_SMOKE_CURSORS=1 MEASURELAB_UI_SMOKE_VIEW=pair \
    ./scripts/cargo.sh run --locked --features qa -- --ui-smoke --compact
MEASURELAB_UI_SMOKE_VIEW=pair MEASURELAB_UI_SMOKE_ADJUST=scope \
    MEASURELAB_UI_SMOKE_SETTINGS=scope \
    ./scripts/cargo.sh run --locked --features qa -- --ui-smoke --compact
MEASURELAB_UI_SMOKE_VIEW=pair MEASURELAB_UI_SMOKE_ADJUST=spectrum \
    MEASURELAB_UI_SMOKE_SETTINGS=spectrum MEASURELAB_SPECTRUM_PSD=1 \
    MEASURELAB_UI_SMOKE_CALIBRATION=1 \
    ./scripts/cargo.sh run --locked --features qa -- --ui-smoke --compact
MEASURELAB_UI_SMOKE_VIEW=spectrum MEASURELAB_UI_SMOKE_ADJUST=analysis \
    MEASURELAB_UI_SMOKE_SETTINGS=hidden \
    ./scripts/cargo.sh run --locked --features qa -- --ui-smoke --compact
MEASURELAB_PROFILE_SECONDS=8 MEASURELAB_PROFILE_LIFECYCLE=1 \
    MEASURELAB_PROFILE_IDLE=1 \
    ./scripts/cargo.sh run --locked --features qa -- --demo
```

## 未確認事項

メニューを開いた画像とプログラムによる状態遷移の確認であり、マウスによる全設定の反復操作・外部仮想I/O・物理入力の一連の測定手順は今回実施していない。600秒・最大FFTの実時間性能、Windows／Linux、異なるDPIと画面寸法も今回の確認範囲に含めない。主要数値・カーソルの文字強調・数値書式は保留し、プロット内の既存表示を維持する。

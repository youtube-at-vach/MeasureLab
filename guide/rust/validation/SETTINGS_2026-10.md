# 測定設定の保存・復元の検証

検証日：2026-10-10。対象は `2301cc03` を基点とする設定保存・復元の未コミット変更を含む作業ツリー。現在の操作は [README](../README.md#測定設定の保存復元)、残る完了条件は [PLAN](../PLAN.md#3d校正と再現に必要な最小保存) に保持する。

## 定義と環境

macOS 14.8.9（23J631）、x86_64、Rust/Cargo 1.99、Metal / AMD Radeon R9 M290X。数値試験は合成f64フレーム、復元UIは合成16chデバイスID、再開・保持の回帰は内部デモを使う。実デバイスの校正精度を評価する試験ではない。

版1のJSONは測定条件と表示設定を分ける。入力はCPALのバックエンド付きID・表示名・CH数・公称Fs選択とDevice defaultのFsを保持する。CH割当・解析条件・校正ID／版／係数／単位／参照条件を次回Start用として保存し、生サンプル・結果・カーソル・取得開始の状態は含めない。読み込みは64 KiBまで、書き込みは同じディレクトリの一時ファイルをflushしてから置換する。専用I/Oワーカーへの要求キューは容量1、UIの未完了要求も1件に制限する。

デバイス不在・重複ID・CH数の変化・非対応Fs・保存時から変わったDevice defaultのFsでは、別の入力へ置き換えず復元全体を拒否する。未知の版・旧形式・未知の項目／列挙値・不正数値も拒否する。校正は既存の検証済みコンストラクターから作り、CH重複やID／版の衝突を拒否する。アプリでは現在の次回用・保持中の定義との衝突も照合する。

## 数値・ファイルI/O

* Spectrumの全10サイズ、f64／f32、3窓、Live／Continuous／LatestのJSON往復を確認した。CH 16／CH 8、負のゲインとf64の下位桁、ID・版・単位・参照条件・表示設定を同じ値で復元した。
* 48 kHz・1,024フレーム・16chでCH 16に `0.125 + 0.25 × sin(2π × 16 × n / 1024)`、CH 8に同振幅のcosを与えた。CH 16のゲイン約−4 V/FS・オフセット約1 V、Hann・PSD・DC除去なし・EMA α = 1で、保存前と読み込み後のScope統計・全PSDビン・窓メタデータが同じだった。理論値のRMS √0.75 V、P-P 2 V、全帯域電力0.75 V²と絶対許容差1e−14で照合した。
* 名前が同じ別IDを選ばず、列挙順が変わっても同じIDを選び、名前の変更は許容した。不在・重複ID・16ch→2ch・非対応48 kHz・Device defaultの48→96 kHzは拒否した。
* 版0／未知の版、版のない旧形式、開始状態の追加、未知のFFT精度、null係数、非有限値、範囲外CH／Fs／FFT長／EMA、校正CHの重複・同じID／版の異なる係数を拒否した。過大ファイルも拒否した。
* 保存ワーカーを終了して新しいワーカーで同じファイルを復元した。不正な定義、作成できない保存先で以前のファイルを維持し、欠落ファイルはエラーにした。新版の係数を保存すると完全な新版で置換され、一時ファイルを残さなかった。
* 新しい入力世代の開始準備では、Spectrogramの容量を再確保せず履歴を無効化し、旧世代の遅着行を拒否した。新世代のconfigure後に同じ容量を再利用して回復した。

GUIを含めないビルドでも設定モジュールの5テストが成功した。設定保存の数値試験は同じ有限入力の再解析であり、実入力やアプリ再起動後のADC測定の成功とは扱わない。

## アプリ・画面の確認

`MEASURELAB_UI_SMOKE_SETTINGS_RESTORE=1`のdev QAで、合成16chデバイスの設定を保存・読み込みし、次を確認した。

* 不在入力・既存校正ID／版と異なる係数・取得中の復元を拒否し、現在の設定を変更しない。
* 復元処理中のStartを拒否し、復元成功でも入力ストリームを開始しない。
* 保持したSpectrumの全f64電力・窓メタデータ、履歴区間、入力世代・Fs・CH数、取得時の校正定義を変更しない。
* 次回用の96 kHz・CH 16・PSD・新版校正を保持結果から分離する。開始準備と以後のUI更新でCH 16を以前の2ch入力へ補正しない。
* `--low-latency`の通常幅・`--compact`で、保存先・Save／Restoreボタン・状態表示と停止状態を撮影した。画像は `dist/settings-restore-ui.png`、`dist/settings-restore-ui-compact.png`、QAファイルは `dist/settings-restore-qa.json`、通常幅ログは `dist/settings-ui.log`。

通常VSyncの内部デモ・ライフサイクルQA（計測5秒＋起動待ち2秒）で、Stop・保持・校正編集・再開・入力切替・非表示・カーソル・遅着除外を回帰確認した。取得・Spectrum入力・無効窓・STFT入力／表示行の欠落は0。停止中は434.5 msの再描画なし区間を確認した。

最終の通常releaseビルドでGPU読み戻しが成功した。Scope／Spectrum／XYの独立、524,288点f64の実ビンピーク、Spectrogramの折り返し・欠落・最大サイズのNyquistと同じ更新番号での再転送省略を確認した。ログは `dist/settings-gpu.log`。

初回の同QAでは停止中の再描画間隔が201 msで、250 msより長いことを要求するidle assertionに失敗した。このときreleaseビルドも実行中だったが、原因は特定していない。最終devビルドで上記の再実行が成功した。低遅延の画面撮影や短い内部デモQAを、通常の長時間性能・外部I/Oの保証に使わない。

## 検証コマンド

```sh
./scripts/cargo.sh fmt --all -- --check
./scripts/cargo.sh clippy --locked --all-targets --all-features -- -D warnings
./scripts/cargo.sh test --locked --all-targets --all-features
./scripts/cargo.sh test --locked --no-default-features --lib settings::tests
./scripts/cargo.sh build --release --locked
./scripts/cargo.sh run --release --locked -- --gpu-smoke
MEASURELAB_UI_SMOKE_SETTINGS_RESTORE=1 ./scripts/debug.sh --ui-smoke --low-latency
MEASURELAB_UI_SMOKE_SETTINGS_RESTORE=1 ./scripts/debug.sh --ui-smoke --low-latency --compact
./.venv/bin/ruff check .
./.venv/bin/ruff format --check .
npx markdownlint-cli2 "**/*.md" "#node_modules"
git diff --check
```

全ターゲット・全機能の115コアテスト・起動オプションの1テストと4ベンチマークが成功した。fmt、全ターゲット・全機能のClippy、通常releaseデスクトップビルド、Ruff check／format check、Markdown lint、`git diff --check`も成功した。ログは `dist/settings-tests.log`、GUIなしの設定テストは `dist/settings-headless-tests.log`。ベンチマークと並行してビルドも行ったため、出力時間を性能比較の実測値には使わない。Markdown用のNode.jsが通常のPATHになかったため、`.tools/env.sh`を読み込んでlintを実行した。

## 残る境界

* 実入力による保存→アプリ終了・再起動→手動復元→既知信号の再測定。外部仮想I/O、物理デバイスでのID・公称Fs・CH・数値の再照合。
* Windows／Linux実機のデバイス識別・ファイル置換・画面確認。デバイスIDの安定性はCPALバックエンドと機器に依存する。
* 結果と条件の書き出し、汎用Software LoopbackとLock-in。
* 起動時の自動復元、自動保存、旧形式の移行は実装していない。測定設定は手動で保存・復元する。

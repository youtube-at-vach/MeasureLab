# 配布版の導入

Rust版は現在公開準備中です。[ダウンロード画面](https://youtube-at-vach.github.io/MeasureLab/download/?edition=rust&lang=ja)ではRustを明示的に選べますが、配布物の公開まではダウンロードできません。Python最終版v0.9.1は同じ画面のPython選択から引き続き利用できます。今試す場合は [ソースから起動](quickstart.md) してください。

## 配布候補と確認範囲

初回は実験段階のプロトタイプをPrereleaseとして扱い、GitHub LatestはPython v0.9.1のままにします。以下はビルド対象であり、各OS版・機器での測定保証ではありません。配布実行ファイルでの起動・実入出力・停止・保存・再起動と復元の受け入れは未完了です。

| OS・CPU | 形式 | ビルド下限・現在の確認範囲 |
| --- | --- | --- |
| Windows 10／11 x64 | Setup／ZIP | MSVC release版。従来のVM起動確認はGNU／dev-fastで、配布版の実入出力・保存復元の確認ではない |
| Linux x86_64 | AppImage／tar.gz | Ubuntu 22.04基準、glibc 2.35以降。Ubuntu 26.04.1・X11のAppImage起動とIntel GPU読み戻しの一条件を確認。実入出力・保存復元・Waylandは未確認 |
| macOS Intel x86_64 | DMG | macOS 13.0以降向け。開発ビルドの測定記録は限定条件。配布DMGからのFinder起動・初回権限・保存復元は未確認 |
| macOS Apple Silicon arm64 | DMG | macOS 13.0以降向け。配布DMGの実機受け入れは未確認 |

Windows ARM64、Linux ARM64／musl（Alpine等）、macOS Universal Binaryはこの配布の対象外です。実行にはPython・Rustの開発環境は不要です。Generator・Lock-in・同期比較の統合評価や、通常GUIの包括的な操作・実モニター間DPIの受け入れは残ります。[機能と既知の制限](index.md) も確認してください。

## ダウンロードの確認

公開後は版・OS・CPU・形式を選び、同じReleaseのOS別`SHA256SUMS-<OS>-<CPU>.txt`と`*-build-info.json`を使って確認します。Python版とRust版ではIntel MacとWindows ZIPの名前が異なります。Rust版は次の名前です。

* Intel Mac：`MeasureLab-v<版>-macos-x86_64.dmg`
* Windows ZIP：`MeasureLab-v<版>-windows-x64.zip`

macOSは`shasum -a 256 <ファイル名>`、Linuxは`sha256sum <ファイル名>`、Windows PowerShellは`Get-FileHash <ファイル名> -Algorithm SHA256`で配布一覧の値と比較できます。`build-info`の版・ソースSHA・通常desktop構成も同じReleaseの説明と照合します。SHA-256はファイルの同一性確認で、発行元認証ではありません。

## Windows

Setupは管理者権限なしでユーザー単位にインストールし、Python版と別の場所・ショートカットを使います。ZIPは展開して`MeasureLab/measurelab.exe`を起動します。公式MSVC版はVisual C++ランタイムを静的リンクします。

実行ファイルとSetupはAuthenticode未署名です。Windowsが発行元を確認できない場合があります。配布元とチェックサムを確認してください。実入力にはWindows設定でデスクトップアプリのマイクアクセスを許可します。音声デバイスとwgpu対応の描画環境が必要です。

## macOS

Apple Siliconは`arm64`、Intel Macは`x86_64`のDMGを選びます。DMGを開き、`MeasureLab.app`をApplicationsへコピーしてDMGを取り出し、Finderから起動します。Python版も同じアプリ名なので、併用する場合は先に別名・別フォルダーへ移してください。

現在はHardened Runtimeと音声入力entitlement付きのad-hoc署名で、Developer ID署名・Appleの公証はありません。Gatekeeperに止められた場合は配布元とチェックサムを確認し、「システム設定 → プライバシーとセキュリティ → このまま開く」が表示されれば使用します。Gatekeeper全体を無効にする必要はありません。

実入力を初めて開始するときにMeasureLabへのマイクアクセスを許可します。外部Core Audio入力も対象です。拒否した場合は「プライバシーとセキュリティ → マイク」でMeasureLabを許可し、アプリを終了・再起動して再試行します。ターミナル経由の起動では権限の帰属が異なるため、配布版の確認にはFinderから起動したアプリを使います。

## Linux

AppImageに実行権限を付けて起動します。ファイル名の`<版>`は取得した版に置き換えます。

```sh
chmod +x MeasureLab-v<版>-linux-x86_64.AppImage
./MeasureLab-v<版>-linux-x86_64.AppImage
```

FUSEを利用できない場合は`--appimage-extract-and-run`を付けるか、tar.gzを展開して`MeasureLab/AppRun`を実行します。両形式のアプリ本体は同じです。

ホスト側のglibc・ALSA設定とプラグイン・X11／Wayland・xkbcommon・wgpu対応GPUドライバーを使用します。最小構成では対応するランタイムパッケージが必要です。発行元署名はありません。

## 起動・保存・更新

入力・出力は停止状態で起動します。デバイスがない場合は [Software Loopback](quickstart.md) で機器なしの取得・停止・保存を試せます。実入力でデバイスが表示されない場合は、OSの権限・接続・デバイスの対応FsとCHを確認します。Generatorの出力開始と入力開始は独立しています。

入出力デバイス・Fs、確定済みの測定条件・校正、画面配置・表示・言語は自動保存して次回起動時に復元します。変更を約2秒ごとに確認し、終了時も最後の変更を書き込みます。復元だけでは入出力を開始しません。機器が不在でも保存した条件を残し、他の機器へ自動で置き換えません。接続変更は入出力停止・ストリーム解放後に行い、**Refresh devices** で再照合してください。

| OS | 自動保存先 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\MeasureLab\startup-preferences.json` |
| macOS | `~/Library/Application Support/MeasureLab/startup-preferences.json` |
| Linux | `$XDG_CONFIG_HOME/MeasureLab/startup-preferences.json`（未指定・空・相対パスは`~/.config/MeasureLab/startup-preferences.json`） |

**File / File paths & status… / STARTUP PREFERENCES** で保存先とエラーを確認できます。破損・未対応版の設定は上書きせず、初期値で起動します。初期化したい場合はアプリを閉じ、このファイルを別名に退避して再起動します。Python版の`config.json`や作業フォルダーのファイルは自動取り込みしません。取得データ・保持結果・カーソルは保存対象外です。入力が未確定の間は直前の有効な測定条件を保持し、初回は表示設定だけを保存します。

設定は版9（旧版1〜8を読み込み）、結果JSONは版6（旧版1〜5を読み込み）です。設定は停止中に復元し、復元だけでは入出力を開始しません。Fileで保存先を選び、Python版とは別のファイルに保存してください。Windowsの既定設定先は`%APPDATA%\MeasureLab\measurement-settings.json`です。

Scope／Spectrumは保持結果のJSON・CSVと表示PNG、Lock-in／同期比較は条件付きJSON・CSVを扱います。Spectrogram／XY・カーソル・全CHの長時間記録は結果保存の対象外です。アプリを更新・削除しても外部へ保存したファイルは保持します。更新前に必要な設定と結果を保存し、再起動後に停止状態で復元してください。

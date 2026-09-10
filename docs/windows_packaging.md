# Windows配布方式とビルド

## 採用方式

PyInstallerのonedir出力をInno Setup 6で包む、ユーザー単位のEXEインストーラーを標準とします。Pythonや依存ライブラリは同梱され、利用者によるPythonのインストールは不要です。既存のonedir ZIPとonefile ZIPも継続します。

| 方法 | 特徴 | 今回の判断 |
| --- | --- | --- |
| Inno Setup / EXE | フォルダー一式の配布、ショートカット、更新、削除を宣言的に構成できる | 採用。既存のビルドを活用でき、ユーザー単位の導入に適する |
| NSIS / EXE | スクリプトによる柔軟なインストール処理 | 実現可能だが、今回必要な標準動作はInno Setupで十分 |
| WiX / MSI | Windows Installerによる製品管理、企業向け展開 | MSIとしての管理要件が具体化した段階で再検討。現状ではコンポーネントと更新の管理が増える |
| MSIX | パッケージID、Store配布や更新との統合 | 配布用署名の基盤整備と既存のファイル配置・オーディオ動作の検証を先に要するため保留 |

判断の根拠は、[Inno Setupの権限設定](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)、[AppIdと更新の対応](https://jrsoftware.org/ishelp/topic_setup_appid.htm)、[NSISの機能](https://nsis.sourceforge.io/Features)、[Windows Installerのメジャーアップグレード](https://learn.microsoft.com/en-us/windows/win32/msi/major-upgrades)、[MSIXの署名要件](https://learn.microsoft.com/en-us/windows/msix/package/signing-package-overview)です。

## インストールと更新の契約

* Windows 10 / 11のx64を対象に、既定で `%LOCALAPPDATA%\Programs\MeasureLab` に配置します。管理者権限やシステム全体へのインストールは要求しません。ARM64上のx64実行はInno Setupの `x64compatible` 判定に従いますが、ネイティブARM64版や実機検証を意味しません。
* `AppId` は全バージョンで固定します。Windowsのアプリ一覧に登録され、同じユーザーの更新時には既存のインストール先を再利用します。
* スタートメニューに登録し、デスクトップショートカットと完了後の起動は任意とします。作業ディレクトリをインストール先に固定して既存のポータブル設定解決と整合させます。
* 更新前にアプリを終了してください。Inno SetupのRestart Manager連携で使用中ファイルを確認し、強制終了や計測の自動再開は指定しません。
* `_internal` はインストーラーが管理する依存ファイル専用とし、更新時に置き換えます。削除されたPythonモジュールや古いDLLの残存を防ぎます。このディレクトリにユーザーデータを保存しないでください。
* `%APPDATA%\MeasureLab`、インストール先の `config.json`、スクリーンショットなどのユーザーファイルは削除しません。ZIP版のローカルファイルは自動移行しません。
* ASIOのDLL切替は更新時にリセットされます。同梱の `enable_asio.bat` で必要に応じて再度有効化します。
* 自動更新機能やWindows Authenticode署名は今回追加しません。既存のSigstore署名とSHA-256チェックサムはインストーラーにも適用します。SigstoreはSmartScreenの発行元認証を代替しません。

## ビルド

リポジトリルートで実行します。Python 3.12の仮想環境、依存関係、PyInstaller、ImageMagick、Inno Setup 6.3以降の6.xが必要です。GitHubのWindowsランナーでは既存のInno Setupを利用し、使用バージョンをログに記録します。ローカルでは [Inno Setup](https://jrsoftware.org/isinfo.php) をインストールしてください。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install pyinstaller
magick app_icon.png -define icon:auto-resize=256,128,64,48,32,16 app_icon.ico
New-Item -ItemType Directory -Force libs
Copy-Item C:\Windows\System32\icu.dll,C:\Windows\System32\icuuc.dll,C:\Windows\System32\icuin.dll libs
.\.venv\Scripts\pyinstaller.exe --noconfirm --windowed --name MeasureLab --icon=app_icon.ico --add-data "src;src" --add-binary "libs/icu*.dll;." --exclude-module matplotlib --collect-all backports --collect-all soundfile --collect-all pyfftw --hidden-import pyfftw --distpath dist/onedir --workpath build/onedir main_gui.py
Copy-Item scripts/enable_asio.bat,scripts/disable_asio.bat,scripts/README_ASIO.txt dist/onedir/MeasureLab/
pwsh -File scripts/build_windows_installer.ps1 -Python .\.venv\Scripts\python.exe
```

バージョンは `pyproject.toml` から読み込みます。出力は `dist/release/MeasureLab-v<version>-windows-x64-setup.exe` です。タグビルドではタグが `v<version>` と一致しないと失敗します。コンパイラーが標準の場所にない場合は `-Iscc` で `ISCC.exe` のパスを指定できます。

## 検証と配布

`build_windows.yml` と `release.yml` の両方で、インストーラーを生成してから `scripts/test_windows_installer.ps1` を実行します。インストーラー定義やスクリプトのみのPRでもWindowsビルドが動き、手動実行も可能です。

テストは使い捨てのWindowsアカウントで実行します。既存のMeasureLabのインストール登録やスタートメニュー項目がある場合は中止します。

```powershell
pwsh -File scripts/test_windows_installer.ps1 -Installer dist/release/MeasureLab-v<version>-windows-x64-setup.exe
```

確認する内容は次のとおりです。

1. 空白・日本語を含むパスへのサイレントインストール。
2. 配布フォルダー全ファイルとのハッシュ一致、ユーザー単位の削除登録、ショートカットのリンク先と作業ディレクトリ。
3. インストール済み実行ファイルの `--self-test` による起動と正常終了。
4. 同一バージョンの再インストールによる更新処理、不要DLLの除去、設定・校正ファイルの保持。
5. 更新後の起動、アンインストールによる登録と実行ファイルの除去、ユーザーファイルの保持。

ログは `dist/installer-test` に保存し、CIの成否にかかわらずアーティファクトとして収集します。リリース処理では検証に成功したEXEをSigstoreで署名し、チェックサムとともに公開し、VirusTotalのスキャン対象にも追加します。

ダウンロードサイトは選択されたバージョンのGitHub Releaseにインストーラーが存在する場合だけ推奨表示します。旧リリース、取得失敗、API制限時は既存のZIP版へフォールバックします。

実機でのオーディオ入出力、一般ユーザーでの対話式ウィザード、実際の旧バージョンからの更新、SmartScreen表示は別途Windowsで確認してください。CIの起動テストは計測機能すべての正常動作を保証するものではありません。

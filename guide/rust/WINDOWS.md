# Windowsでのビルドと起動確認

リポジトリのルートでPowerShellから実行する。Rustの最小要件は1.95、以下の起動確認は1.99.0を使用した。macOS／Linux用の`setup_dev_env.sh`や`debug.sh`はネイティブWindows用ではない。

標準構成と公式配布ビルドはRustのMSVCツールチェーンとVisual Studio C++ Build Tools（C++デスクトップ開発・Windows SDK）。ネイティブ起動では、まず下記のMSVC構成を使う。GNU／LLDはMSVCを導入しない環境向けの代替手順として分ける。起動確認と音声測定・配布物の受け入れは別に判定する。確認環境と未確認範囲は [VALIDATION](VALIDATION.md#コードで代替できない確認の要約) を参照する。

## MSVCでのセットアップ

### GitとC++ビルドツール

PowerShell 7を使い、まず`git --version`でGitを確認する。GitHub Desktopだけを導入した環境では、同梱GitがPATHにない場合がある。その場合は [Git for Windows](https://gitforwindows.org/) を導入するか、既存の同梱Gitを現在のPowerShellだけで使う。

```powershell
$desktopGit = Get-ChildItem "$env:LOCALAPPDATA/GitHubDesktop/app-*/resources/app/git/cmd/git.exe" |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $desktopGit) { throw 'Git for Windowsを導入してください。' }
$env:PATH = "$($desktopGit.DirectoryName);$env:PATH"
git status --short --branch
```

[Microsoftのコマンドライン導入手順](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio)に従い、C++デスクトップ開発と推奨コンポーネントのWindows SDKを導入する。Windowsの管理者確認が必要になる。既存のVisual Studioがある場合は、そのインストーラーで同じコンポーネントを追加できる。

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools --exact --source winget `
    --silent --accept-package-agreements --accept-source-agreements `
    --override '--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended'
if ($LASTEXITCODE -ne 0) { throw 'Build Toolsの導入結果を確認してください。' }

& "${env:ProgramFiles(x86)}/Microsoft Visual Studio/Installer/vswhere.exe" `
    -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
    -property installationPath
```

ツール・インストーラーのキャッシュと、`dev-fast`／通常テスト／releaseのビルド成果物は別々に容量を使う。小さなWindowsパーティションでは、導入前とビルド中に`Get-PSDrive C`で空き容量を確認する。既存データやOS管理ファイルを削除して容量を確保しない。休止状態などのOS設定変更は開発環境の必須手順にしない。

### ローカルRust

[公式rustup](https://rust-lang.org/tools/install/)のWindows x64版を取得し、プロジェクト内へRust 1.99.0・rustfmt・Clippyを導入する。システムのPATHや既存Rust環境は変更しない。

```powershell
New-Item -ItemType Directory -Force .tools/downloads | Out-Null
Invoke-WebRequest https://win.rustup.rs/x86_64 -OutFile .tools/downloads/rustup-init.exe
$env:CARGO_HOME = Join-Path $PWD '.tools/cargo'
$env:RUSTUP_HOME = Join-Path $PWD '.tools/rustup'
& ./.tools/downloads/rustup-init.exe -y --no-modify-path --profile minimal `
    --default-host x86_64-pc-windows-msvc --default-toolchain 1.99.0 `
    --component rustfmt --component clippy
if ($LASTEXITCODE -ne 0) { throw 'Rustの導入に失敗しました。' }
$env:PATH = "$env:CARGO_HOME/bin;$env:PATH"
if (-not $env:RUST_BACKTRACE) { $env:RUST_BACKTRACE = '1' }
rustc -Vv
cargo --version
```

新しいPowerShellでも`CARGO_HOME`・`RUSTUP_HOME`・PATHを設定する。毎回使う設定はGit管理外の`.tools/env.ps1`へ保存し、`. ./.tools/env.ps1`で読み込める。MSVC構成ではGNU用の`WINDRES`・`AR`・`RUSTFLAGS`・LLDの指定を追加しない。以前のGNU環境から切り替える場合は、新しいPowerShellで設定する。

### ビルド・起動・検証

```powershell
cargo build --locked --profile dev-fast
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
& ./target/dev-fast/measurelab.exe --help
& ./target/dev-fast/measurelab.exe --gpu-smoke
& ./target/dev-fast/measurelab.exe --compact
```

通常の起動は入力・出力停止から始まる。内部デモや自動UI確認を使う場合だけ`qa`を追加する。

ネイティブ起動でも実GPUのドライバーがない場合は、`--gpu-smoke`がMicrosoft Basic Render Driverによるソフトウェア描画で成功することがある。アダプター名とバックエンドを記録し、成功をハードウェア描画や測定性能の確認へ広げない。[iMacでの確認範囲](VALIDATION.md#windowsネイティブでの開発環境と起動確認)を参照する。

```powershell
cargo run --locked --profile dev-fast --features qa -- --ui-smoke
```

PR前は [共通検証](../../.agents/workflows/tool_usage.md#rust-アプリ) と同じ構成をPowerShellで実行する。Cargoは通常のPowerShellからVisual Studio／SDKを検出するため、まず追加のリンカー指定なしで確認する。

容量が少ない場合は、検証専用のPowerShellで次を指定するとシンボルとインクリメンタル成果物を省ける。検証結果にこの設定を記録し、日常の開発や完全なデバッガー情報が必要な作業は新しいPowerShellで実行する。

```powershell
$env:CARGO_PROFILE_DEV_DEBUG = '0'
$env:CARGO_PROFILE_TEST_DEBUG = '0'
$env:CARGO_INCREMENTAL = '0'
```

```powershell
cargo fmt --all -- --check
cargo clippy --locked --all-targets --all-features -- -D warnings
cargo test --locked --no-default-features
cargo test --locked
cargo test --locked --all-targets --all-features
cargo test --locked --doc --all-features
cargo build --release --locked
```

PowerShellは外部コマンドの非ゼロ終了だけでは後続処理を止めない。一括実行する場合は各コマンド直後の`$LASTEXITCODE`を確認し、失敗した検証を成功扱いしない。

### サイト・文書用ツール

Node.js／npmとPython 3.12以降も必要。[セットアップの使用版](SETUP.md#導入先とツール)に合わせたWindows x64版のNode.jsとuvを使える。公式アーカイブと配布元のSHA-256を照合してから`.tools/`へ展開し、Node.jsと`uv.exe`のディレクトリを現在のPATHへ追加する。Pythonはuvで導入できる。

```powershell
$env:UV_PYTHON_INSTALL_DIR = Join-Path $PWD '.tools/python'
$env:UV_PYTHON_BIN_DIR = Join-Path $PWD '.tools/bin'
$env:UV_CACHE_DIR = Join-Path $PWD '.tools/uv-cache'
$env:PYTHONUTF8 = '1'
uv python install 3.13
uv venv --seed --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements-docs.txt ruff
& ./.venv/Scripts/python.exe -m pip check
npm.cmd --prefix download-site ci
npm.cmd --prefix download-site test
& ./.venv/Scripts/python.exe scripts/build_pages.py
& ./.venv/Scripts/ruff.exe check .
& ./.venv/Scripts/ruff.exe format --check .
& ./.venv/Scripts/python.exe -m unittest discover -s scripts -p 'test_ci_changes.py'
& ./.venv/Scripts/python.exe -m unittest discover -s scripts -p 'test_i18n.py'
& ./.venv/Scripts/python.exe scripts/i18n.py check --base <基準SHA>
```

ネイティブWindowsの仮想環境は`.venv/bin/`ではなく`.venv/Scripts/`を使う。Storeへの案内用`python.exe`だけがPATHにある状態を、Pythonの導入済みと判断しない。既存の`.venv`がある場合はPython版・用途を確認して再利用し、上書きや削除をしない。Markdown lintはWindows版Node.jsで`npx.cmd markdownlint-cli2 "**/*.md" "#node_modules"`を実行する。通常のサイト操作も`npm.cmd`を使えばPowerShellの`npm.ps1`実行ポリシーに依存しない。

i18nのGitスナップショット回帰テストでは、日本語・空白を含むファイル名を全OSで確認する。[Windowsで禁止される制御文字](https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file#naming-conventions)に当たる改行入りファイル名のケースだけをWindowsではskipし、対応OSで検証する。

## MSVCを導入しない環境（GNU／LLD）

以下はVisual Studio C++ Build Toolsを導入していないVMで使った代替構成。[VMでの確認条件](VALIDATION.md#windows-vmでの起動確認)に限る結果であり、ネイティブ環境に同じリンカー問題があるとは判断しない。

### ローカルツールの準備

[公式rustup](https://rust-lang.org/tools/install/)からWindows x64用の`rustup-init.exe`を取得し、`.tools/downloads/rustup-init.exe`へ置く。RustとCargoの保存先をプロジェクト内へ指定し、システムのPATHを変更せずGNUツールチェーンを導入する。既存の開発環境は上書きしない。

```powershell
New-Item -ItemType Directory -Force .tools/downloads | Out-Null
$env:CARGO_HOME = Join-Path $PWD '.tools/cargo'
$env:RUSTUP_HOME = Join-Path $PWD '.tools/rustup'
& ./.tools/downloads/rustup-init.exe -y --no-modify-path --profile minimal `
    --default-host x86_64-pc-windows-gnu --default-toolchain 1.99.0
```

[LLVM-MinGW 20261006の公式配布](https://github.com/mstorsjo/llvm-mingw/releases/tag/20261006)から`llvm-mingw-20261006-ucrt-x86_64.zip`を取得する。今回使用したZIPのSHA-256は`317492c456aa27ee607a5919f1d2d38dcdc1112516a24d0bf4b00d078f52d17a`。

ZIPを展開し、`bin`内の`llvm-dlltool.exe`、`ld.lld.exe`とDLL一式を`.tools/llvm-dlltool/`へコピーする。その後、Rustが検索する名前で`llvm-dlltool.exe`をコピーする。

Windows実行ファイルにはCargoの版・製品名と既存のアプリアイコンを埋め込む。GNUビルドでは追加で`windres`と`ar`が必要になる。LLVM-MinGWの展開済みディレクトリをそのまま保持し、`WINDRES`／`AR`環境変数で`bin/llvm-windres.exe`／`bin/llvm-ar.exe`の絶対パスを指定する。プリプロセッサーとヘッダーも使うため、この2ファイルだけをコピーしない。LLVM-MinGWの`bin`全体をRust GNUのリンカーより優先してPATHへ入れると、GCC互換ラッパーがRustのGCCライブラリを見つけられなくなる場合がある。MSVCビルドではWindows SDKの`rc.exe`を使う。

たとえばZIPを`.tools/llvm-resources/`へ展開した場合は、新しいPowerShellで次も設定する。

```powershell
$resourceBin = (Resolve-Path '.tools/llvm-resources/llvm-mingw-20261006-ucrt-x86_64/bin').Path
$env:WINDRES = Join-Path $resourceBin 'llvm-windres.exe'
$env:AR = Join-Path $resourceBin 'llvm-ar.exe'
```

```powershell
Copy-Item .tools/llvm-dlltool/llvm-dlltool.exe .tools/llvm-dlltool/dlltool.exe
```

`dlltool.exe`だけが見つからない構成ではWindowsライブラリをコンパイルできない。Rust同梱のGNU `dlltool.exe`だけをPATHへ追加する方法も、別途アセンブラーがない今回の環境では動かなかった。LLVM版を使用することでこの追加依存を避けられた。

`.tools/`、`target/`とQA成果物の`dist/`はGit管理外。ツールやビルド生成物をコミットしない。

### GNUビルドと起動

新しいPowerShellでは、毎回以下の環境を設定する。保存先が異なる既存のRust環境を使う場合は、その環境に合わせる。

```powershell
$env:CARGO_HOME = Join-Path $PWD '.tools/cargo'
$env:RUSTUP_HOME = Join-Path $PWD '.tools/rustup'
$gnuToolchain = Join-Path $env:RUSTUP_HOME 'toolchains/1.99.0-x86_64-pc-windows-gnu'
$gnuBin = Join-Path $gnuToolchain 'lib/rustlib/x86_64-pc-windows-gnu/bin/self-contained'
$env:PATH = "$env:CARGO_HOME/bin;$PWD/.tools/llvm-dlltool;$gnuBin;$env:PATH"

cargo rustc --locked --profile dev-fast --bin measurelab -- `
    -C linker-flavor=ld -C linker=.tools/llvm-dlltool/ld.lld.exe `
    -C link-self-contained=yes
```

`cargo rustc`の追加引数はアプリ本体のリンクへ適用する。依存ライブラリは通常のGNU構成でビルドする。今回のGNU既定リンカーでの`cargo build`は完了したが、生成した実行ファイルは`--help`の段階からアクセス違反（`0xC0000005`）で終了した。LLDでリンクした同じソースは起動できたため、上記ではLLDとRust同梱のリンク用ライブラリを明示する。

```powershell
& ./target/dev-fast/measurelab.exe --help
& ./target/dev-fast/measurelab.exe --gpu-smoke
& ./target/dev-fast/measurelab.exe --compact
```

`--help`でCLIの起動、`--gpu-smoke`で描画と読み戻し、通常GUIで初期画面とメニュー応答をそれぞれ確認する。`--compact`は小さな画面向けの起動サイズ指定。入力・出力は停止状態から始まる。起動確認だけで音声の取得やGeneratorの出力を開始する必要はない。

初回は依存ライブラリの取得・コンパイルに時間がかかる。2論理CPU・4 GiBのVMではビルド中のメモリ使用量にも余裕が少ない。`dev-fast`の起動結果をrelease版の性能評価へ読み替えない。

## VMでの描画方式

起動後の**Help**にバックエンドとアダプター名が表示される。今回のVMでは、環境変数による描画指定なしで`Dx12 · Microsoft Basic Render Driver`が選ばれ、通常GUIと`--gpu-smoke`が動作した。ソフトウェア描画による起動確認であり、VMwareのハードウェア3D描画や実時間の測定性能を確認した結果ではない。

OpenGLは今回の確認では使用していない。必要な環境では、egui-wgpuが読む`WGPU_BACKEND`を現在のPowerShell内で指定できる。ただし、対応するOpenGL／EGLドライバーがない環境での起動を保証する指定ではない。

```powershell
$env:WGPU_BACKEND = 'gl'
& ./target/dev-fast/measurelab.exe --compact
Remove-Item Env:WGPU_BACKEND
```

DirectXの問題を調べる前に`--help`も確認する。`--help`自体が失敗する場合は描画初期化前の問題として、実行ファイルとツールチェーンを切り分ける。

## Windows配布パッケージの作成

PowerShell 7、Rust 1.99.0のMSVCツールチェーン、Visual Studio C++ Build Tools／Windows SDK、Gitを用意し、リポジトリのルートで実行する。Inno Setupは公式6.7.3のハッシュを照合して`.tools/inno-setup/`へ導入する。管理者権限・Pythonのアプリ依存環境は不要。

```powershell
./scripts/install_inno_setup.ps1
$package = ./scripts/build_windows_installer.ps1
./scripts/test_windows_installer.ps1 -Installer $package.installer `
    -SourceDir $package.source_dir -Archive $package.archive
Invoke-Item $package.release_dir
```

出力は実行ごとの`dist/windows/<id>/release/`。インストーラー、ZIP、build-info、SHA-256が揃う。`-Iscc <ISCC.exeのパス>`で導入済みのInno Setup 6.3以降の6.xも使える。テストはRust版の登録やショートカットが既にあるアカウントでは停止する。日本語・空白を含む一時パスへインストールし、修復・削除後に登録を片付けるため、使い捨てアカウントやVMで実行する。ログは`dist/windows-installer-test/`に残す。

MSVCのないVMでは、上記GNU／LLD・リソースコンパイラーの環境を準備したうえで、次のように実験用パッケージを作れる。build-infoの`target`で公式MSVC版と区別する。Release workflowはGNU版を受け付けない。

```powershell
$package = ./scripts/build_windows_installer.ps1 -Target x86_64-pc-windows-gnu `
    -GnuLinker .tools/llvm-dlltool/ld.lld.exe
./scripts/test_windows_installer.ps1 -Installer $package.installer `
    -SourceDir $package.source_dir -Archive $package.archive
```

release版はGUIサブシステムを使用し、通常起動でコンソールを開かない。CLIの結果を確認する場合は標準出力・標準エラーをリダイレクトし、終了を待つ。

```powershell
Start-Process ./target/x86_64-pc-windows-msvc/release/measurelab.exe `
    -ArgumentList '--help' -Wait -WindowStyle Hidden `
    -RedirectStandardOutput .tools/measurelab-help.txt
Get-Content .tools/measurelab-help.txt
```

GitHubでのartifact作成とDraft Releaseの運用は [公開準備](RELEASE_PREPARATION.md#windows配布) を参照する。インストーラー検証はGPU・音声測定の受け入れを代用しない。

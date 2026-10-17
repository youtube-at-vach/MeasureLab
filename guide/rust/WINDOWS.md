# Windowsでのビルドと起動確認

リポジトリのルートでPowerShellから実行する。Rustの最小要件は1.95、以下の起動確認は1.99.0を使用した。macOS／Linux用の`setup_dev_env.sh`や`debug.sh`はネイティブWindows用ではない。

標準構成と公式配布ビルドはRustのMSVCツールチェーンとVisual Studio C++ Build Tools（C++デスクトップ開発・Windows SDK）。以下は、これらを導入していないWindows VMで起動を確認したGNU／LLDの構成であり、MSVC版やWindows上の測定機能の受け入れを代用しない。確認環境と未確認範囲は [VALIDATION](VALIDATION.md#windows-vmでの起動確認) を参照する。

## ローカルツールの準備

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

## ビルドと起動

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

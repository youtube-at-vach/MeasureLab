// Presentation copy is shared by both editions; release status comes from metadata.
export const pageMessages = {
  ja: {
    navDownload: "ダウンロード",
    navManual: "マニュアル",
    skipLink: "ダウンロードへ移動",
    heroTitle: "信号を、",
    heroAccent: "もっと鮮明に。",
    heroIntro: "PCを、あなたの測定器に。",
    heroBody:
      "音を可視化し、信号を確かめる。オープンソースのオーディオ測定ツール、MeasureLab。",
    heroAction: "Python v0.9.1 を入手",
    heroRustAction: "Rust {version} を入手",
    pythonAvailable: "公開中・最終版",
    rustAvailable: "公開中・プロトタイプ",
    heroSecondary: "Rust版について",
    preparing: "Rust版は公開準備中",
    available: "Rustプロトタイプ公開中",
    signalCaption: "信号を見つめる、その先へ。",
    signalNote: "波形はイメージです",
    principleOne: "正確な測定を。",
    principleTwo: "無料で。",
    principleThree: "すべての人へ。",
    editionLabel: "エディション",
    platformLabel: "プラットフォーム",
    formatLabel: "CPU・パッケージ",
    recommended: "この端末",
    packageHelp: "パッケージの選び方",
    packageHelpData: {
      macOS:
        "メニュー →「このMacについて」で確認できます。「チップ」がApple Mシリーズなら Apple Silicon、「プロセッサ」がIntelなら Intel を選んでください。",
      Windows:
        "通常はインストーラーを選んでください。インストールせずに使う場合は、ZIP版を展開して起動します。いずれもx64向けです。",
      Linux:
        "AppImageに実行権限を付けて起動してください。x86_64向けのパッケージです。",
    },
    windowsZipHelp:
      "ZIP版を展開し、MeasureLab.exeを起動してください。Windows x64向けのパッケージです。",
    linuxRustHelp:
      "通常はAppImageを選んで実行権限を付けてください。FUSEが使えない場合はtar.gzを展開し、MeasureLab/AppRunを起動します。いずれもx86_64向けです。",
    footerLinks: "関連リンク",
    downloadFor: "{os}版をダウンロード",
    unavailable: "公開準備中",
    requirementsTitle: "動作環境と初回起動について",
    legacyNotice: "Python最終版 v0.9.1 をダウンロードします。",
    rustNotice: "Rust版は準備中です。バイナリはまだ公開していません。",
    rustExperimental:
      "プロトタイプでは、Generator・Lock-in・同期2ch比較は実験段階です。",
    footerNote: "正確な測定を、無料で、すべての人へ。",
    sourceLink: "ソースコード",
    languageLabel: "表示言語",
  },
  en: {
    navDownload: "Download",
    navManual: "Manual",
    skipLink: "Skip to downloads",
    heroTitle: "Every signal.",
    heroAccent: "A clearer view.",
    heroIntro: "Your computer. Your measurement bench.",
    heroBody:
      "See your sound. Understand your signals. An open-source audio measurement tool for your computer.",
    heroAction: "Get Python v0.9.1",
    heroRustAction: "Get Rust {version}",
    pythonAvailable: "Available · final edition",
    rustAvailable: "Available · prototype",
    heroSecondary: "Explore Rust",
    preparing: "Rust edition in preparation",
    available: "Rust prototype available",
    signalCaption: "Look closer. See further.",
    signalNote: "Illustrative waveform",
    principleOne: "Accurate measurement.",
    principleTwo: "Free to use.",
    principleThree: "For everyone.",
    editionLabel: "Edition",
    platformLabel: "Platform",
    formatLabel: "CPU & package",
    recommended: "This device",
    packageHelp: "Which package should I choose?",
    packageHelpData: {
      macOS:
        "Open the Apple menu → About This Mac. Choose Apple Silicon if Chip shows an Apple M-series chip, or Intel if Processor shows Intel.",
      Windows:
        "Choose the installer for a standard installation. To use the app without installing it, extract the ZIP package and launch it. Both are for x64.",
      Linux:
        "Make the AppImage executable before launching it. This package is for x86_64.",
    },
    windowsZipHelp:
      "Extract the ZIP package and launch MeasureLab.exe. This package is for Windows x64.",
    linuxRustHelp:
      "Choose AppImage and make it executable. If FUSE is unavailable, extract tar.gz and launch MeasureLab/AppRun. Both are for x86_64.",
    footerLinks: "Explore",
    downloadFor: "Download for {os}",
    unavailable: "In preparation",
    requirementsTitle: "System requirements & first launch",
    legacyNotice: "You’re downloading the final Python edition, v0.9.1.",
    rustNotice:
      "The Rust edition is in preparation. Binaries are not available yet.",
    rustExperimental:
      "Generator, Lock-in and synchronous 2ch comparison are experimental in the prototype.",
    footerNote: "Accurate measurement. Free. For everyone.",
    sourceLink: "Source code",
    languageLabel: "Display language",
  },
  zh: {
    navDownload: "下载",
    navManual: "手册",
    skipLink: "跳转至下载",
    heroTitle: "让信号，",
    heroAccent: "更加清晰。",
    heroIntro: "让你的电脑，成为你的测量仪器。",
    heroBody:
      "让声音可见，让信号易懂。MeasureLab，你的开源音频测量工具。",
    heroAction: "获取 Python v0.9.1",
    heroRustAction: "获取 Rust {version}",
    pythonAvailable: "已发布 · 最终版",
    rustAvailable: "已发布 · 原型",
    heroSecondary: "了解 Rust 版",
    preparing: "Rust 版正在准备发布",
    available: "Rust 原型已发布",
    signalCaption: "看得更细，理解更深。",
    signalNote: "波形为示意图",
    principleOne: "准确测量。",
    principleTwo: "免费使用。",
    principleThree: "面向所有人。",
    editionLabel: "版本",
    platformLabel: "平台",
    formatLabel: "CPU 与软件包",
    recommended: "当前设备",
    packageHelp: "应该选择哪个软件包？",
    packageHelpData: {
      macOS:
        "打开苹果菜单 →“关于本机”。“芯片”显示 Apple M 系列时请选择 Apple Silicon；“处理器”显示 Intel 时请选择 Intel。",
      Windows:
        "通常请选择安装程序。如需免安装使用，请解压 ZIP 软件包后启动。两种软件包均适用于 x64。",
      Linux: "请先为 AppImage 添加执行权限后再启动。此软件包适用于 x86_64。",
    },
    windowsZipHelp:
      "请解压 ZIP 软件包并启动 MeasureLab.exe。此软件包适用于 Windows x64。",
    linuxRustHelp:
      "通常请选择 AppImage 并添加执行权限。无法使用 FUSE 时，请解压 tar.gz 并启动 MeasureLab/AppRun。两种软件包均适用于 x86_64。",
    footerLinks: "相关链接",
    downloadFor: "下载 {os} 版",
    unavailable: "正在准备发布",
    requirementsTitle: "系统要求与首次启动",
    legacyNotice: "你将下载 Python 最终版本 v0.9.1。",
    rustNotice: "Rust 版正在准备中，尚未提供二进制下载。",
    rustExperimental:
      "原型中的 Generator、Lock-in 和同步双通道比较处于实验阶段。",
    footerNote: "准确测量，免费提供，面向所有人。",
    sourceLink: "源代码",
    languageLabel: "显示语言",
  },
};

// Distribution guidance is separate from the final Python edition's guidance.
export const rustMessages = {
  ja: {
    editionLabel: "使用する版",
    pythonEdition: "Python 最終版",
    rustEdition: "Rust プロトタイプ",
    releaseDetails: "リリースノート・チェックサム・ビルド情報",
    unpublished: "公開準備中 · ダウンロードはまだ利用できません。",
    publishedNotice: "Rust プロトタイプです。Generator・Lock-in・同期2ch比較は実験段階で、配布物での確認範囲はマニュアルを参照してください。",
    docsLink: "Rust マニュアル",
    releaseSize: "サイズはリリースページを参照",
    labels: {
      arm64: "Apple Silicon · arm64 · DMG",
      x86_64: "Intel · x86_64 · DMG",
      installer: "x64 · インストーラー",
      zip: "x64 · ZIP",
      appimage: "x86_64 · AppImage",
      targz: "x86_64 · tar.gz",
    },
    requirementData: {
      macOS: {
        lead: "macOS 13.0以降向けのビルドです。OS版・機器ごとの受け入れは未完了です。",
        items: [
          "Apple Siliconはarm64、Intelはx86_64。DMGからApplicationsへコピーし、DMGを取り出して起動してください。Python版は先に別名・別フォルダーへ退避してください。",
          "ad-hoc署名で、Developer ID署名・公証はありません。配布元とSHA-256を確認し、必要なら「システム設定 > プライバシーとセキュリティ > このまま開く」を使ってください。",
          "実入力の開始時にマイクアクセスを許可してください。拒否後は「プライバシーとセキュリティ > マイク」で許可し、アプリを再起動します。外部Core Audio入力も対象です。",
        ],
      },
      Windows: {
        lead: "Windows 10 / 11 x64向けです。MSVC配布版での実入出力・保存復元は未受け入れです。",
        items: [
          "Setupはユーザー単位でインストールします。ZIPは展開してmeasurelab.exeを起動します。Python・Rustの導入は不要です。",
          "Authenticode未署名です。OS別SHA256SUMSで同一性を確認してください。チェックサムは発行元認証ではありません。",
          "実入力にはWindows設定でデスクトップアプリのマイクアクセスを許可してください。",
        ],
      },
      Linux: {
        lead: "glibc 2.35以降のLinux x86_64向けです（Ubuntu 22.04基準）。実入出力・Wayland・保存復元などの受け入れは未完了です。",
        items: [
          "AppImageにchmod +xで実行権限を付けます。FUSEが使えなければ--appimage-extract-and-run、またはtar.gzを展開してMeasureLab/AppRunを実行します。",
          "ホストのALSA・X11／Wayland・xkbcommonとwgpu対応GPUドライバーが必要です。ARM64・musl／Alpine向けの配布はありません。",
          "発行元署名はありません。OS別SHA256SUMSとbuild-infoのソースSHAを確認してください。",
        ],
      },
    },
  },
  en: {
    editionLabel: "Choose an edition",
    pythonEdition: "Final Python edition",
    rustEdition: "Rust prototype",
    releaseDetails: "Release notes, checksums and build information",
    unpublished: "In preparation · Downloads are not available yet.",
    publishedNotice: "Rust prototype. Generator, Lock-in and synchronous comparison are experimental. See the manual for package acceptance limits.",
    docsLink: "Rust manual",
    releaseSize: "See release for size",
    labels: {
      arm64: "Apple Silicon · arm64 · DMG",
      x86_64: "Intel · x86_64 · DMG",
      installer: "x64 · Installer",
      zip: "x64 · ZIP",
      appimage: "x86_64 · AppImage",
      targz: "x86_64 · tar.gz",
    },
    requirementData: {
      macOS: {
        lead: "Built for macOS 13.0 or later. OS-version and device acceptance remains incomplete.",
        items: [
          "Choose arm64 for Apple Silicon or x86_64 for Intel. Copy the app to Applications, eject the DMG, then launch. Keep the Python app under another name or in another folder first.",
          "Ad-hoc signed, without Developer ID signing or notarization. Verify the source and SHA-256, then use System Settings > Privacy & Security > Open Anyway if needed.",
          "Allow microphone access when starting real input, including external Core Audio devices. After denial, enable it under Privacy & Security > Microphone and relaunch.",
        ],
      },
      Windows: {
        lead: "For Windows 10 / 11 x64. Physical I/O and save/restore acceptance of the MSVC package remains incomplete.",
        items: [
          "Setup installs for your account. For ZIP, extract and run measurelab.exe. No Python or Rust installation is required.",
          "Not Authenticode signed. Check the platform's SHA256SUMS; checksums identify files but do not authenticate the publisher.",
          "Allow microphone access for desktop apps in Windows Settings to use real input.",
        ],
      },
      Linux: {
        lead: "For glibc 2.35+ Linux x86_64, built on Ubuntu 22.04. Physical I/O, Wayland and save/restore acceptance remains incomplete.",
        items: [
          "Run chmod +x on the AppImage. Without FUSE, use --appimage-extract-and-run or extract tar.gz and run MeasureLab/AppRun.",
          "Requires host ALSA, X11/Wayland, xkbcommon and a wgpu-compatible GPU driver. No ARM64 or musl/Alpine package is provided.",
          "No publisher signature. Verify the platform's SHA256SUMS and source SHA in build-info.",
        ],
      },
    },
  },
  zh: {
    editionLabel: "选择版本",
    pythonEdition: "Python 最终版本",
    rustEdition: "Rust 原型",
    releaseDetails: "发布说明、校验和及构建信息",
    unpublished: "正在准备发布 · 暂不可下载。",
    publishedNotice: "Rust 原型。Generator、Lock-in 和同步双通道比较处于实验阶段。请参阅手册中的软件包验收范围。",
    docsLink: "Rust 手册",
    releaseSize: "大小请参阅发布页面",
    labels: {
      arm64: "Apple Silicon · arm64 · DMG",
      x86_64: "Intel · x86_64 · DMG",
      installer: "x64 · 安装程序",
      zip: "x64 · ZIP",
      appimage: "x86_64 · AppImage",
      targz: "x86_64 · tar.gz",
    },
    requirementData: {
      macOS: {
        lead: "面向 macOS 13.0 或更高版本构建。各系统版本及设备的验收尚未完成。",
        items: [
          "Apple Silicon 选择 arm64，Intel 选择 x86_64。复制到 Applications，推出 DMG 后再启动。请先为 Python 应用更名或移到其他文件夹。",
          "采用 ad-hoc 签名，无 Developer ID 签名及公证。确认来源及 SHA-256 后，必要时在“系统设置 > 隐私与安全性”选择“仍要打开”。",
          "启动实际输入时请允许麦克风访问，外部 Core Audio 设备也需要此权限。拒绝后可在“隐私与安全性 > 麦克风”中允许并重新启动应用。",
        ],
      },
      Windows: {
        lead: "适用于 Windows 10 / 11 x64。MSVC 软件包的实际输入输出和保存恢复验收尚未完成。",
        items: [
          "Setup 为当前用户安装。ZIP 版解压后运行 measurelab.exe。无需安装 Python 或 Rust。",
          "无 Authenticode 签名。请核对对应平台的 SHA256SUMS；校验和不能认证发布者。",
          "使用实际输入时，请在 Windows 设置中允许桌面应用访问麦克风。",
        ],
      },
      Linux: {
        lead: "适用于 glibc 2.35+ Linux x86_64，以 Ubuntu 22.04 为构建基准。实际输入输出、Wayland 和保存恢复验收尚未完成。",
        items: [
          "通过 chmod +x 授予 AppImage 执行权限。无法使用 FUSE 时，可添加 --appimage-extract-and-run，或解压 tar.gz 后运行 MeasureLab/AppRun。",
          "需要系统提供 ALSA、X11/Wayland、xkbcommon 及兼容 wgpu 的 GPU 驱动。未提供 ARM64 或 musl/Alpine 软件包。",
          "无发布者签名。请核对对应平台的 SHA256SUMS 和 build-info 中的源代码 SHA。",
        ],
      },
    },
  },
};

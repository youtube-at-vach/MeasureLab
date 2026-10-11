# MeasureLab

[English](README.md)

**正確な測定を、無料で、すべての人へ。** MeasureLabは、PCを使うオーディオ測定・解析アプリです。Rust版は取得・測定演算・GPU描画を分離し、ScopeとSpectrumで条件と結果を再現できる測定を目指しています。

**現在はソースから試せるRustプロトタイプです。** Scope／Spectrumの捕捉・校正・結果再利用を実装し、通常ビルドでSoftware Loopbackを使えます。Lock-inは実験段階です。実機精度・長時間動作・OS対応には未確認の範囲があります。[実装計画](guide/rust/PLAN.md) と [検証記録](guide/rust/validation/README.md) を参照してください。

## 現在使える機能

| 測定器・機能 | Rust版の実装範囲 |
| --- | --- |
| オーディオ入力 | CPALによる1〜16ch同期入力、取得後のf64サンプル、対応する公称サンプルレートの選択 |
| Scope | 任意2ch、Auto／Normal／Single、Autoset、RMS・Peak・P-P、時間カーソルと取得保持 |
| Spectrum | 1,024〜524,288点、振幅／PSD、帯域電力・RMS、平均、ピーク保持、周波数カーソル |
| Spectrogram／XY | 独立したSTFT表示と、同期2chを選べるXY表示 |
| 校正・結果の再利用 | CHごとのゲイン・オフセット・単位、版付き設定、Scope／SpectrumのJSON・CSV・PNG、参照比較 |
| Software Loopback | 既知のゲイン・位相・遅延・雑音を共通入力から評価。物理出力は行わない |
| 実験段階のLock-in | 基本波のREF／応答測定、X/Y・R/θ、Gainと整定状態 |

測定コアはf64を基準にし、選択可能なf32 FFTは数値上の制限を分けて扱います。表示を閉じても解析・平均は続きます。結果には取得条件を対応付け、欠落や無効な値を正常なゼロで代用しません。

物理信号出力、THD／FRF／IR、VST3、実サンプル時計の校正、旧Python版の多数の測定器はRust版では未実装です。Scopeの波形軸とトリガーはFSで、校正した数値読み出しとは区別します。Lock-inの実機REF・タイミングは未検証です。

## プロトタイプの起動

Rust 1.95以降と各OSのビルド環境が必要です。Rustの統合先は現在`rewrite/rust`で、今回の公開準備ではまだ`main`へ切り替えません。

```sh
git clone --branch rewrite/rust https://github.com/youtube-at-vach/MeasureLab.git
cd MeasureLab
cargo run --release --locked
```

このコマンドはRustの統合ブランチを取得します。作業ブランチ上の最新機能はまだ含まれない場合があります。新しいmacOS／Linux環境では [セットアップガイド](guide/rust/SETUP.md) に従い、ローカルツールをまとめて用意できます。

```sh
./scripts/setup_dev_env.sh --install-os-deps --verify
source .tools/env.sh
./scripts/debug.sh
```

アプリは停止状態で起動します。入力デバイスを選んで **Start input** を押すか、**Input source → Software Loopback** を選ぶと機器なしで試せます。**View → Scope + Spectrum** と **Adjust** で表示・測定条件を調整し、**Stop** で保持して **File** から設定・結果を保存できます。48 kHz・512kの完全窓は約10.92秒を要し、Liveの更新頻度を上げても短くなりません。

| OS | ビルド環境と現在の確認範囲 |
| --- | --- |
| macOS | Xcode Command Line Tools。実入力にはマイク許可が必要。条件を限定したmacOS／BlackHole／GPU検証記録あり |
| Linux | C/C++ツール、pkg-config、ALSA・X11・Wayland・xkbcommonの開発ライブラリ。CI対象で、実機音声・GPU動作は未確認 |
| Windows | RustのMSVCツールチェーンとVisual Studio C++ Build Tools。CI対象で、実機音声・GPU動作は未確認 |

macOSのローカルアプリバンドルは`./scripts/bundle-macos.sh`で作れます。公開用のRustインストーラー・署名・対応OS／CPUは [公開準備](guide/rust/RELEASE_PREPARATION.md) の課題です。QA専用デモは`./scripts/debug.sh --demo`を使います。通常のSoftware LoopbackにはQAビルドは不要です。

## マニュアルとPython v0.9.1

| 版 | 案内 | 入手方法 |
| --- | --- | --- |
| Rustプロトタイプ | [利用者向けマニュアル原稿](docs-rust/index.md)、[詳細な操作ガイド](guide/rust/README.md)、[セットアップ](guide/rust/SETUP.md) | 現在はソースからビルド |
| Python最終版 | [保存版オンラインマニュアル](https://youtube-at-vach.github.io/MeasureLab/) | [ダウンロードサイト](https://youtube-at-vach.github.io/MeasureLab/download/)・[v0.9.1リリース](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1) |

Python版の開発はv0.9.1で終了しました。完全なソースと旧ビルド手順は [タグ](https://github.com/youtube-at-vach/MeasureLab/tree/v0.9.1) と [archiveブランチ](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1) に残します。Rust公開後も旧マニュアルの既存URLを維持します。新マニュアルは`/MeasureLab/rust/`、英語版は`/MeasureLab/rust/en/`への公開を準備しており、Pagesデプロイ後に利用できます。ダウンロード案内と`version.json`はPython v0.9.1のままです。

## 開発・フィードバック

[現在の方針](guide/CURRENT_DIRECTION.md) → [実装計画](guide/rust/PLAN.md) の順に参照してください。リポジトリ・CI・配布・オンライン文書のタスクは [公開準備](guide/rust/RELEASE_PREPARATION.md) に分けています。Rust、CPAL、RustFFT、egui / eframe、wgpuを使い、Pythonは文書・リリース用ツールだけに使用します。

AI支援を含む [貢献](CONTRIBUTING.md) を歓迎します。PRの宛先は現在`rewrite/rust`です。CIは3 OS、通常／QA／GUIなしの構成、最小Rust版、workflow、新旧マニュアルとダウンロードを対象にします。ローカルの手順は [Tool Usage Guide](.agents/workflows/tool_usage.md) を参照してください。CIの成功は物理測定の精度保証ではありません。

[不具合報告](https://github.com/youtube-at-vach/MeasureLab/issues) には、版とコミット、OS・GPU、入力機器、Fs・CH・FFT設定、再現手順を添えてください。脆弱性の報告は [Security Policy](SECURITY.md) に従ってください。

## 📜 ライセンス

このプロジェクトは **The Unlicense** の下でパブリックドメインとして公開されています。Rust 版も従来の MeasureLab と同じライセンスを継続します。全文は [LICENSE](LICENSE) を参照してください。

## 👥 コントリビューター

### 🧑‍💻 スペシャルサンクス

- [Dominique Michel](https://github.com/domichel)
- [Major Wong(diyAudio)](https://www.diyaudio.com/community/members/major-wong.345860/)
- [TNT (diyAudio)](https://www.diyaudio.com/community/members/tnt.4571/)
- [fantastictaste6171](https://www.youtube.com/@fantastictaste6171)
- [バーチャ農ちゃんねる](https://www.youtube.com/@va-ch)

### 🤖 AI パートナー

- OpenAI: GPT-4.1, GPT-5, GPT-5.1 Codex Max, GPT-5.2, GPT-5.2 Codex, GPT-5.3-Codex, GPT-5.4, GPT-5.5, GPT-5.6, GPT-6 Astra
- Google: Gemini 2.5 Pro, Gemini 3 Pro, Gemini 3 Flash, Gemini 3.1 Pro, Gemini 3.5 Frash
- Anthropic: Claude 4.5 Sonnet

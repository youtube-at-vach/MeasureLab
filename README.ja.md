# MeasureLab

[English](README.md)

MeasureLab は DIY のオーディオ測定・解析ツール集です。このブランチでは Rust 版への移行準備を進めています。

Python/PyQt6 版の最終リリースは [v0.9.1](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1) です。完全なソースはこのタグと [archive/python-v0.9.1 ブランチ](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1) から参照できます。

## ダウンロードとマニュアル

- [ダウンロードサイト](https://youtube-at-vach.github.io/MeasureLab/download/)
- [オンラインマニュアル](https://youtube-at-vach.github.io/MeasureLab/)
- [Python v0.9.1 のソース・開発ガイド](https://github.com/youtube-at-vach/MeasureLab/blob/v0.9.1/docs/development.md)

ダウンロードサイトと既存のマニュアルは Python 版の案内として継続して利用します。

## Rust 移行の状態

このブランチでは Python アプリ本体、テスト、アプリのビルド環境を退役させました。Rust 実装はまだ取り込んでいません。

`download-site/`、マニュアル生成用ファイル、開発履歴、測定・設計資料、アイコンを残しています。残したファイルと退避先の詳細は [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md)、現在の検証コマンドは [Contributing](CONTRIBUTING.md) を参照してください。

## 📜 ライセンス

このプロジェクトは **The Unlicense** の下でパブリックドメインとして公開されています。
営利・非営利を問わず、自由にコピー、変更、配布、使用することができます。

> **注**: 本ソフトウェアはパブリックドメインとして公開された、自由で制約のないソフトウェアです。

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

# MeasureLab

[English](README.md)

MeasureLab は「正確な測定を、無料で、すべての人へ。」を目指すオーディオ測定・解析アプリです。このブランチには Rust のプロトタイプがあり、1〜16ch のオーディオ入力、オシロスコープ、スペクトル、スペクトログラム、XY 表示、内部デモ信号に対応しています。

Python/PyQt6 版の最終リリースは [v0.9.1](https://github.com/youtube-at-vach/MeasureLab/releases/tag/v0.9.1) です。完全なソースはこのタグと [archive/python-v0.9.1 ブランチ](https://github.com/youtube-at-vach/MeasureLab/tree/archive/python-v0.9.1) から参照できます。

## ダウンロードとマニュアル

- [ダウンロードサイト](https://youtube-at-vach.github.io/MeasureLab/download/)
- [オンラインマニュアル](https://youtube-at-vach.github.io/MeasureLab/)
- [Python v0.9.1 のソース・開発ガイド](https://github.com/youtube-at-vach/MeasureLab/blob/v0.9.1/docs/development.md)

ダウンロードサイトと既存のマニュアルは Python 版の案内として継続して利用します。

## Rust 移行の状態

このブランチでは Python アプリ本体、テスト、アプリのビルド環境を退役させました。Rust 開発の PR は `rewrite/rust` に向け、配布済みの Python 版は別途維持します。

Rust 1.95 以降と OS のビルドツールを用意した環境では、次のコマンドでデモを起動できます。

```sh
./scripts/cargo.sh run --release --locked -- --demo
```

設計原則は [現在の方針](guide/CURRENT_DIRECTION.md)、実装の制限と次の完了条件は [開発計画](guide/rust/PLAN.md) を参照してください。当面は取得・測定演算を UI 更新から独立させ、Scope と Spectrum の測定用途を完成させます。対応機能、実オーディオ入力、各 OS の前提は [Rust 版の操作・ビルドガイド](guide/rust/README.md) にまとめています。

`download-site/`、マニュアル生成用ファイル、開発履歴、測定・設計資料、アイコンを残しています。残したファイルと退避先の詳細は [Rust rewrite preparation](guide/RUST_REWRITE_PREPARATION.md)、現在の検証コマンドは [Contributing](CONTRIBUTING.md) を参照してください。

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

# Decky Translator LLM

A fork of [Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) — Gemini Vision で Steam Deck の画面を直接翻訳するプラグイン。

## Overview

[Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Deck. スクリーンショットを Gemini Vision API に送り、テキスト検出と翻訳を1パスで実行します。従来の OCR → テキスト翻訳パイプラインと異なり、画面コンテキストを理解した高品質な翻訳が得られます。

バックエンドは OpenAI API 互換エンドポイントであれば何でも使えます。

## Features

- スクリーンショットからの直接翻訳（OCR不要）
- カスタムプロンプト（共通 / ゲーム別）
- OpenAI API 互換の任意のバックエンドに対応

### 対応バックエンド

* Google Gemini（gemini-2.5-flash, gemini-2.5-flash-lite 等）
* OpenAI API 互換サービス（Ollama, vLLM, LiteLLM 等）

## Installation

Decky公式ストアには登録していません。手動インストールのみ。

### Requirements

* Steam Deck（LCD / OLED）
* [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
* LLMサービスのAPIキー

## Settings

| 設定項目 | 説明 |
| --- | --- |
| Gemini API Key | Gemini / OpenAI互換サービスのAPIキー |
| Gemini Model | モデル名（例: `gemini-2.5-flash-lite`） |
| Base URL（Advanced） | APIエンドポイント。未設定時はGoogle Gemini APIを使用 |

### Prompts

翻訳の挙動をプロンプトファイルでカスタマイズできます:

* **共通プロンプト** — 全ゲームに適用。Prompts タブまたは SSH で `~/homebrew/settings/decky-translator-prompts/vision-common.txt` を編集
* **ゲーム別プロンプト** — 特定ゲーム起動中のみ適用。`~/homebrew/settings/decky-translator-games/{app_id}/vision.txt` を編集

## License

GNU GPLv3 — オリジナルと同一ライセンス。

## Credits

* Original: [cat-in-a-box/Decky-Translator](https://github.com/cat-in-a-box/Decky-Translator)
* See [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) for third-party dependencies

# Decky Translator LLM

[Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) のフォーク — Gemini Vision で Steam Deck の画面を直接翻訳するプラグイン。

[English](README.md)

## 概要

Steam Deck 用の [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) プラグインです。スクリーンショットを Gemini Vision API に送り、テキスト検出と翻訳を1パスで実行します。従来の OCR → テキスト翻訳パイプラインと異なり、画面コンテキストを理解した高品質な翻訳が得られます。

バックエンドは OpenAI API 互換エンドポイントであれば何でも使えます。

## 特徴

* スクリーンショットからの直接翻訳（OCR不要）
* カスタムプロンプト（共通 / ゲーム別）
* OpenAI API 互換の任意のバックエンドに対応

### 対応バックエンド

* Google Gemini（gemini-2.5-flash, gemini-2.5-flash-lite 等）
* OpenAI API 互換サービス（Ollama, vLLM, LiteLLM 等）

## インストール

Decky公式ストアには登録していません。手動インストールのみ。

### 必要なもの

* Steam Deck（LCD / OLED）
* [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
* LLMサービスのAPIキー

### URLからインストール

1. ゲームモードでDeckyメニューを開く（QAM / `...` ボタン）
2. 設定（歯車アイコン）→ **General** → **Developer Mode** を有効化
3. **Developer** タブ → **Install Plugin from URL** を選択
4. 以下のURLを貼り付け:
   ```
   https://github.com/worldnine/Decky-Translator-LLM/releases/latest/download/Translator.LLM.zip
   ```
5. Decky Loaderを再起動（設定 → General → **Restart Decky**）

## 設定

| 設定項目 | 説明 |
| --- | --- |
| Gemini API Key | Gemini / OpenAI互換サービスのAPIキー |
| Gemini Model | モデル名（例: `gemini-2.5-flash-lite`） |
| Base URL（Advanced） | APIエンドポイント。未設定時はGoogle Gemini APIを使用 |

### プロンプト

翻訳の挙動をプロンプトファイルでカスタマイズできます:

* **共通プロンプト** — 全ゲームに適用。Prompts タブまたは SSH で `~/homebrew/settings/decky-translator-prompts/vision-common.txt` を編集
* **ゲーム別プロンプト** — 特定ゲーム起動中のみ適用。`~/homebrew/settings/decky-translator-games/{app_id}/vision.txt` を編集

## ライセンス

GNU GPLv3 — オリジナルと同一ライセンス。

## クレジット

* オリジナル: [cat-in-a-box/Decky-Translator](https://github.com/cat-in-a-box/Decky-Translator)
* サードパーティ依存については [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) を参照

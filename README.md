# Decky Translator LLM

A fork of [Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) — translate your Steam Deck screen directly with Gemini Vision.

[日本語](README.ja.md)

## Overview

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for Steam Deck. Sends screenshots to the Gemini Vision API, performing text detection and translation in a single pass. Unlike traditional OCR → translation pipelines, the LLM sees the full screen context for higher quality translations of game text.

Any OpenAI API-compatible endpoint can be used as the backend.

## Features

* Direct screenshot-to-translation (no separate OCR step)
* Custom prompts (global and per-game)
* Works with any OpenAI API-compatible backend

### Supported backends

* Google Gemini (gemini-2.5-flash, gemini-2.5-flash-lite, etc.)
* Any OpenAI API-compatible service (Ollama, vLLM, LiteLLM, etc.)

## Installation

This plugin is NOT available on the Decky Plugin Store. Manual installation only.

### Requirements

* Steam Deck (LCD or OLED)
* [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
* An API key for your LLM service

## Settings

| Setting | Description |
| --- | --- |
| Gemini API Key | API key for Gemini or any OpenAI-compatible service |
| Gemini Model | Model name (e.g. `gemini-2.5-flash-lite`) |
| Base URL (Advanced) | API endpoint. Defaults to Google Gemini API if left empty |

### Prompts

Customize translation behavior with prompt files:

* **Common prompt** — Applied to all games. Edit from the Prompts tab or via SSH at `~/homebrew/settings/decky-translator-prompts/vision-common.txt`
* **Per-game prompt** — Applied only while a specific game is running. Edit at `~/homebrew/settings/decky-translator-games/{app_id}/vision.txt`

## License

GNU GPLv3 — same license as the original.

## Credits

* Original: [cat-in-a-box/Decky-Translator](https://github.com/cat-in-a-box/Decky-Translator)
* See [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) for third-party dependencies

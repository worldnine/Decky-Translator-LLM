# Decky Translator LLM

A fork of [Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) with Gemini Vision-based translation.

## Overview

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that captures your Steam Deck screen and translates text directly using Gemini Vision API. Unlike traditional OCR + translation pipelines, the LLM sees the screenshot and performs text detection and translation in a single pass, providing context-aware translations of game text.

Any OpenAI API-compatible endpoint can be used as the backend.

## What's different from the original?

| Feature | Original | This fork |
| --- | --- | --- |
| Google Translate / Cloud Translation | o | - (removed) |
| OCR (RapidOCR, OCR.space, Google Vision) | o | - (removed) |
| Gemini Vision (screenshot -> translation) | x | o |
| Custom prompts (common / per-game) | x | o |

This fork is specialized for Gemini Vision direct translation. The original multi-provider OCR and translation pipeline has been removed in favor of a simpler, single-pass architecture.

### Supported backends (OpenAI API compatible)

* Google Gemini (gemini-2.5-flash, gemini-2.5-flash-lite, etc.)
* Any OpenAI API-compatible service (Ollama, vLLM, LiteLLM, etc.)

## Decky Plugin Store

This plugin is NOT available on the Decky Plugin Store. Manual installation only.

## Requirements

* Steam Deck (LCD or OLED)
* [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
* An API key for your LLM service

## Settings

| Setting | Description |
| --- | --- |
| Gemini API Key | API key for the Gemini / OpenAI-compatible service |
| Gemini Model | Model name (e.g. `gemini-2.5-flash-lite`) |
| Base URL (Advanced) | API endpoint. Defaults to Google's Gemini API |

### Prompts

You can customize translation behavior with prompt files:

* **Common prompt** — Applied to all games. Edit from the Prompts tab or via SSH at `~/homebrew/settings/decky-translator-prompts/vision-common.txt`
* **Per-game prompt** — Applied only when a specific game is running. Edit from the Prompts tab or at `~/homebrew/settings/decky-translator-games/{app_id}/vision.txt`

## License

GNU GPLv3 — same license as the original.

## Credits

* Original: [cat-in-a-box/Decky-Translator](https://github.com/cat-in-a-box/Decky-Translator)
* See [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) for third-party dependencies

# Decky Translator LLM

A fork of [Decky Translator](https://github.com/cat-in-a-box/Decky-Translator) with LLM-based translation support via OpenAI-compatible APIs.

## Overview

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin that captures text on your Steam Deck screen using OCR and translates it using LLMs (Large Language Models). LLMs can understand game context for higher quality translations compared to traditional machine translation.

All original translation providers (Google Translate, Google Cloud Translation) are still available.

## What's different from the original?

| Feature                                 | Original | This fork |
| --------------------------------------- | -------- | --------- |
| Google Translate                        | o        | o         |
| Google Cloud Translation                | o        | o         |
| LLM Translation (OpenAI API compatible) | x        | o         |

### Supported LLM services (any OpenAI API compatible service)

* Google Gemini (gemini-2.5-flash-lite, etc.)

* OpenAI (gpt-5.4-mini, etc.)

* DeepSeek

* Ollama (local)

* Any other OpenAI API compatible service

## Decky Plugin Store

This plugin is NOT available on the Decky Plugin Store. Manual installation only.

## Requirements

* Steam Deck (LCD or OLED)

* [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)

* An API key for your LLM service (not needed for Ollama)

## Text Recognition (OCR)

Same providers as the original are available.

| Provider                                               | Description                                              | Requirements       |
| ------------------------------------------------------ | -------------------------------------------------------- | ------------------ |
| [RapidOCR](https://github.com/RapidAI/RapidOCR)        | On-device OCR. Screenshots never leave your device       | -                  |
| [OCR.space](https://ocr.space/)                        | Free cloud-based OCR API                                 | Internet           |
| [Google Cloud Vision](https://cloud.google.com/vision) | Best accuracy and speed. Great for complex/stylized text | Internet + API key |

## License

GNU GPLv3 - same license as the original.

## Credits

* Original: [cat-in-a-box/Decky-Translator](https://github.com/cat-in-a-box/Decky-Translator)

* See [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES) for third-party dependencies

⠀
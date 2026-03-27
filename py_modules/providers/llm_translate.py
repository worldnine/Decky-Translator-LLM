# providers/llm_translate.py
# OpenAI API互換のLLM翻訳プロバイダー
# Gemini Flash, GPT-4o-mini, DeepSeek, Ollama等に対応

import asyncio
import json
import logging
import re
from typing import List

import requests

from .base import TranslationProvider, ProviderType, NetworkError, ApiKeyError

logger = logging.getLogger(__name__)

# デフォルトのシステムプロンプト
DEFAULT_SYSTEM_PROMPT = (
    "You are a game text translator. "
    "Translate the following text from {source_lang} to {target_lang}. "
    "Translate ONLY the text, preserve any formatting. "
    "Return translations in the same order, one per line. "
    "If the input appears to be a UI element or game term, keep it natural for gamers. "
    "Do NOT add any explanations, notes, or extra text."
)


class LlmTranslateProvider(TranslationProvider):
    """OpenAI API互換のLLM翻訳プロバイダー。"""

    # LLMは多くの言語に対応しているため、幅広いリストを持つ
    SUPPORTED_LANGUAGES = [
        'auto', 'en', 'ja', 'zh-CN', 'zh-TW', 'ko', 'de', 'fr', 'es',
        'it', 'pt', 'ru', 'ar', 'el', 'fi', 'nl', 'pl', 'tr', 'uk',
        'hi', 'th', 'vi', 'id', 'ro', 'bg', 'cs', 'da', 'hu', 'no',
        'sv', 'sk', 'hr', 'lt', 'lv', 'et', 'sl', 'ms', 'tl',
    ]

    # 言語コードから自然言語名へのマッピング（プロンプト用）
    LANGUAGE_NAMES = {
        'auto': 'auto-detect',
        'en': 'English', 'ja': 'Japanese', 'zh-CN': 'Simplified Chinese',
        'zh-TW': 'Traditional Chinese', 'ko': 'Korean', 'de': 'German',
        'fr': 'French', 'es': 'Spanish', 'it': 'Italian', 'pt': 'Portuguese',
        'ru': 'Russian', 'ar': 'Arabic', 'el': 'Greek', 'fi': 'Finnish',
        'nl': 'Dutch', 'pl': 'Polish', 'tr': 'Turkish', 'uk': 'Ukrainian',
        'hi': 'Hindi', 'th': 'Thai', 'vi': 'Vietnamese', 'id': 'Indonesian',
        'ro': 'Romanian', 'bg': 'Bulgarian', 'cs': 'Czech', 'da': 'Danish',
        'hu': 'Hungarian', 'no': 'Norwegian', 'sv': 'Swedish', 'sk': 'Slovak',
        'hr': 'Croatian', 'lt': 'Lithuanian', 'lv': 'Latvian', 'et': 'Estonian',
        'sl': 'Slovenian', 'ms': 'Malay', 'tl': 'Filipino',
    }

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        system_prompt: str = "",
        disable_thinking: bool = True,
    ):
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._api_key = api_key
        self._model = model
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._disable_thinking = disable_thinking
        logger.debug(
            f"LlmTranslateProvider initialized: base_url={self._base_url}, "
            f"model={self._model}, disable_thinking={self._disable_thinking}"
        )

    @property
    def name(self) -> str:
        return f"LLM ({self._model or 'unconfigured'})"

    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.LLM

    def configure(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        system_prompt: str = "",
        disable_thinking: bool = None,
    ) -> None:
        """設定を更新する。"""
        if base_url:
            self._base_url = base_url.rstrip("/")
        if api_key:
            self._api_key = api_key
        if model:
            self._model = model
        if system_prompt:
            self._system_prompt = system_prompt
        if disable_thinking is not None:
            self._disable_thinking = disable_thinking

    def _get_language_name(self, lang_code: str) -> str:
        """言語コードを自然言語名に変換する。"""
        return self.LANGUAGE_NAMES.get(lang_code, lang_code)

    def _build_system_prompt(self, source_lang: str, target_lang: str) -> str:
        """翻訳用のシステムプロンプトを構築する。"""
        src_name = self._get_language_name(source_lang)
        tgt_name = self._get_language_name(target_lang)
        return self._system_prompt.format(
            source_lang=src_name, target_lang=tgt_name
        )

    def _call_api(self, messages: list, temperature: float = 0.1) -> str:
        """OpenAI API互換エンドポイントを呼び出す。"""
        if not self._base_url or not self._model:
            raise ApiKeyError("LLM base_url and model must be configured")

        url = f"{self._base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
        }

        # thinkingモード無効化: Ollama等が対応する "think" パラメータを送信
        # 非対応サーバーは未知のパラメータを無視するため安全
        if self._disable_thinking:
            payload["think"] = False

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=30.0
            )

            if response.status_code == 401:
                raise ApiKeyError("Invalid API key")
            if response.status_code == 429:
                from .base import RateLimitError
                raise RateLimitError("Rate limit exceeded")
            if response.status_code != 200:
                logger.warning(
                    f"LLM API error: {response.status_code} - {response.text[:200]}"
                )
                raise NetworkError(f"LLM API returned status {response.status_code}")

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            # thinkingモード対応: <think>...</think> タグを除去
            # DeepSeek-R1, Qwen3等がインラインで思考内容を含む場合がある
            content = self._strip_thinking_tags(content)
            return content.strip()

        except requests.exceptions.ConnectionError as e:
            logger.error(f"LLM connection error: {e}")
            raise NetworkError("LLMサーバーに接続できません") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"LLM timeout: {e}")
            raise NetworkError("LLMサーバーがタイムアウトしました") from e
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"LLM response parse error: {e}")
            raise NetworkError("LLMのレスポンスを解析できません") from e

    @staticmethod
    def _strip_thinking_tags(text: str) -> str:
        """thinkingモードのタグを除去する。

        DeepSeek-R1, Qwen3等はレスポンスに <think>...</think> を含む場合がある。
        また <reasoning>...</reasoning> 等の亜種にも対応する。
        """
        # <think>...</think> (改行を含む)
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        # <reasoning>...</reasoning>
        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
        return text.strip()

    def is_available(self, source_lang: str = "auto", target_lang: str = "en") -> bool:
        """base_urlとmodelが設定されていればTrueを返す。"""
        return bool(self._base_url) and bool(self._model)

    def get_supported_languages(self) -> List[str]:
        return self.SUPPORTED_LANGUAGES.copy()

    def _maybe_append_no_think(self, text: str) -> str:
        """disable_thinking有効時、ユーザーメッセージに /no_think を付加する。

        Qwen3等は /no_think をプロンプト末尾に付けるとthinkingを抑制する。
        非対応モデルはただのテキストとして無視するため安全。
        """
        if self._disable_thinking:
            return text + " /no_think"
        return text

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text or not text.strip():
            return text

        system_prompt = self._build_system_prompt(source_lang, target_lang)
        user_content = self._maybe_append_no_think(text)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.debug(f"LLM translate: {source_lang} -> {target_lang}, len={len(text)}")
        result = await asyncio.to_thread(self._call_api, messages)
        return result

    async def translate_batch(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        if not texts:
            return texts

        # テキストが1つだけの場合は単一翻訳を使う
        if len(texts) == 1:
            translated = await self.translate(texts[0], source_lang, target_lang)
            return [translated]

        system_prompt = self._build_system_prompt(source_lang, target_lang)

        # バッチ翻訳用のプロンプトを構築
        # 番号付きで送信し、番号付きで受信する（行数の不一致を防ぐ）
        numbered_lines = []
        for i, text in enumerate(texts, 1):
            numbered_lines.append(f"[{i}] {text}")
        user_content = "\n".join(numbered_lines)

        batch_instruction = (
            f"Translate the following {len(texts)} texts. "
            "Each line is numbered with [N]. "
            "Return ONLY the translations, one per line, with the same [N] numbering. "
            "Do NOT add any extra text or explanations."
        )

        full_user_content = self._maybe_append_no_think(
            f"{batch_instruction}\n\n{user_content}"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": full_user_content},
        ]

        logger.debug(
            f"LLM batch translate: {len(texts)} texts, "
            f"{source_lang} -> {target_lang}"
        )

        try:
            result = await asyncio.to_thread(self._call_api, messages)
            translated = self._parse_batch_response(result, len(texts))

            if len(translated) == len(texts):
                return translated

            # 行数が一致しない場合、個別に翻訳にフォールバック
            logger.warning(
                f"LLM batch response line mismatch: expected {len(texts)}, "
                f"got {len(translated)}. Falling back to individual translation."
            )
            return await self._translate_individually(texts, source_lang, target_lang)

        except Exception as e:
            logger.error(f"LLM batch translation error: {e}")
            # エラー時は個別翻訳にフォールバック
            return await self._translate_individually(texts, source_lang, target_lang)

    def _parse_batch_response(self, response: str, expected_count: int) -> List[str]:
        """バッチレスポンスをパースして翻訳テキストのリストを返す。"""
        lines = response.strip().split("\n")
        translations = []

        for line in lines:
            line = line.strip()
            if not line:
                continue
            # [N] プレフィックスを除去
            if line.startswith("[") and "]" in line:
                bracket_end = line.index("]")
                line = line[bracket_end + 1:].strip()
            translations.append(line)

        return translations

    async def _translate_individually(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        """個別に翻訳する（フォールバック用）。"""
        results = []
        for text in texts:
            try:
                translated = await self.translate(text, source_lang, target_lang)
                results.append(translated)
            except Exception as e:
                logger.warning(f"Individual translation failed: {e}")
                results.append(text)
        return results

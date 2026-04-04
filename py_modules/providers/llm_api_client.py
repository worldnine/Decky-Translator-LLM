# providers/llm_api_client.py
# OpenAI API互換 / Gemini ネイティブAPIの共通呼び出しクライアント

import json
import logging
import re
from typing import Optional

import requests

from .base import NetworkError, ApiKeyError, RateLimitError, ConfigurationError

logger = logging.getLogger(__name__)


class LlmApiClient:
    """OpenAI API互換 / Gemini ネイティブAPI呼び出しの共通クライアント。

    LlmTranslateProvider と GeminiVisionProvider で共用する。
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        disable_thinking: bool = True,
    ):
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._api_key = api_key
        self._model = model
        self._disable_thinking = disable_thinking

    def configure(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        disable_thinking: bool = None,
    ) -> None:
        """設定を更新する。Noneでない値のみ更新。"""
        if base_url is not None:
            self._base_url = base_url.rstrip("/") if base_url else ""
        if api_key is not None:
            self._api_key = api_key
        if model is not None:
            self._model = model
        if disable_thinking is not None:
            self._disable_thinking = disable_thinking

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def api_key(self) -> str:
        return self._api_key

    @property
    def model(self) -> str:
        return self._model

    @property
    def disable_thinking(self) -> bool:
        return self._disable_thinking

    def is_configured(self) -> bool:
        """base_urlとmodelが設定されているか。"""
        return bool(self._base_url) and bool(self._model)

    def is_gemini(self) -> bool:
        """GeminiネイティブAPIを使うべきか判定する。
        モデル名がgemini-で始まり、かつbase_urlがGoogleのネイティブAPIの場合のみ。
        OpenRouter/LiteLLM等のプロキシ経由の場合はOpenAI互換APIを使う。"""
        return (
            self._model.strip().lower().startswith("gemini-")
            and "generativelanguage.googleapis.com" in self._base_url
        )

    def call(
        self, messages: list, temperature: float = 0.1,
        response_format: dict = None,
        max_tokens: int = None,
        timeout: float = 30.0,
    ) -> str:
        """LLM APIを呼び出す。Geminiの場合はネイティブAPIを使用。

        Raises:
            ConfigurationError: base_url/model未設定
            ApiKeyError: APIキー不正
            NetworkError: ネットワークエラー
            RateLimitError: レート制限
        """
        if not self._base_url or not self._model:
            raise ConfigurationError("LLMのbase_urlとmodelを設定してください")

        if self.is_gemini():
            return self._call_gemini_native(
                messages, temperature, response_format, max_tokens, timeout,
            )

        return self._call_openai_compatible(
            messages, temperature, response_format, max_tokens, timeout,
        )

    def _call_gemini_native(
        self, messages: list, temperature: float,
        response_format: dict, max_tokens: int, timeout: float,
    ) -> str:
        """Gemini ネイティブAPIを呼び出す。thinkingConfig対応。"""
        base = self._base_url
        # 複数の接尾辞を繰り返し剥がす（例: /v1beta/openai/chat/completions → /v1beta）
        changed = True
        while changed:
            changed = False
            for suffix in ["/chat/completions", "/openai", "/v1"]:
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    changed = True
        url = f"{base}/models/{self._model}:generateContent"

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["x-goog-api-key"] = self._api_key

        # OpenAI messages → Gemini contents 変換
        system_text = ""
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if isinstance(content, str):
                    system_text = content
                continue

            gemini_role = "user" if role == "user" else "model"
            parts = []
            if isinstance(content, str):
                parts.append({"text": content})
            elif isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item["text"]})
                    elif item.get("type") == "image_url":
                        img_url = item["image_url"]["url"]
                        if img_url.startswith("data:"):
                            mime_end = img_url.index(";")
                            mime_type = img_url[5:mime_end]
                            b64_data = img_url.split(",", 1)[1]
                            parts.append({
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": b64_data,
                                }
                            })

            if parts:
                contents.append({"role": gemini_role, "parts": parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }

        if system_text:
            payload["systemInstruction"] = {"parts": [{"text": system_text}]}

        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        if response_format and response_format.get("type") == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"
            schema = response_format.get("schema")
            if schema:
                payload["generationConfig"]["responseSchema"] = schema

        if self._disable_thinking:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout,
            )

            if response.status_code == 401 or response.status_code == 403:
                raise ApiKeyError("Invalid API key")
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            if response.status_code != 200:
                logger.warning(
                    f"Gemini API error: {response.status_code} - {response.text[:300]}"
                )
                raise NetworkError(f"Gemini API returned status {response.status_code}")

            result = response.json()
            # トークン使用量をログ出力（キャッシュ確認用）
            usage = result.get("usageMetadata")
            if usage:
                logger.info(
                    f"Gemini tokens: prompt={usage.get('promptTokenCount', '?')}, "
                    f"completion={usage.get('candidatesTokenCount', '?')}, "
                    f"cached={usage.get('cachedContentTokenCount', 'N/A')}"
                )
            candidate = result["candidates"][0]
            finish_reason = candidate.get("finishReason", "unknown")
            content = candidate["content"]["parts"][0]["text"]

            if finish_reason not in ("STOP", "stop"):
                logger.warning(
                    f"Gemini finish_reason={finish_reason} "
                    f"(content length={len(content)})"
                )

            content = self.strip_thinking_tags(content)
            return content.strip()

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Gemini connection error: {e}")
            raise NetworkError("Geminiサーバーに接続できません") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"Gemini timeout: {e}")
            raise NetworkError("Geminiサーバーがタイムアウトしました") from e
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Gemini response parse error: {e}")
            raise NetworkError("Geminiのレスポンスを解析できません") from e

    def _call_openai_compatible(
        self, messages: list, temperature: float,
        response_format: dict, max_tokens: int, timeout: float,
    ) -> str:
        """OpenAI API互換エンドポイントを呼び出す。"""
        url = f"{self._base_url}/chat/completions"
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

        if response_format:
            fmt = {k: v for k, v in response_format.items() if k != "schema"}
            schema = response_format.get("schema")
            if schema:
                fmt = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_translation",
                        "schema": schema,
                    },
                }
            payload["response_format"] = fmt
        if max_tokens:
            payload["max_tokens"] = max_tokens

        # thinkingモード無効化: ローカルサーバー等の緩いサーバーのみに送信
        is_lenient_server = any(h in self._base_url for h in [
            "localhost", "127.0.0.1", "dashscope.", "ollama",
        ])
        if self._disable_thinking and is_lenient_server:
            payload["think"] = False
            payload["enable_thinking"] = False
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout,
            )

            if response.status_code == 401:
                raise ApiKeyError("Invalid API key")
            if response.status_code == 429:
                raise RateLimitError("Rate limit exceeded")
            if response.status_code != 200:
                logger.warning(
                    f"LLM API error: {response.status_code} - {response.text[:200]}"
                )
                raise NetworkError(f"LLM API returned status {response.status_code}")

            result = response.json()
            # トークン使用量をログ出力（キャッシュ確認用）
            usage = result.get("usage")
            if usage:
                cached = usage.get(
                    "cached_tokens",
                    (usage.get("prompt_tokens_details") or {}).get("cached_tokens", "N/A"),
                )
                logger.info(
                    f"LLM tokens: prompt={usage.get('prompt_tokens', '?')}, "
                    f"completion={usage.get('completion_tokens', '?')}, "
                    f"cached={cached}"
                )
            choice = result["choices"][0]
            finish_reason = choice.get("finish_reason", "unknown")
            content = choice["message"]["content"]
            if finish_reason != "stop":
                logger.warning(
                    f"LLM finish_reason={finish_reason} "
                    f"(content length={len(content)})"
                )
            content = self.strip_thinking_tags(content)
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
    def strip_thinking_tags(text: str) -> str:
        """thinkingモードのタグを除去する。

        DeepSeek-R1, Qwen3等はレスポンスに <think>...</think> を含む場合がある。
        また <reasoning>...</reasoning> 等の亜種にも対応する。
        """
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
        return text.strip()

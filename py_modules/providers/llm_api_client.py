# providers/llm_api_client.py
# OpenAI API互換 / Gemini ネイティブAPIの共通呼び出しクライアント

import json
import logging
import random
import re
import time
from typing import Callable, Optional

import requests

from .base import NetworkError, ApiKeyError, RateLimitError, ConfigurationError

logger = logging.getLogger(__name__)

# リトライ設定
# Primary モデル（preview系）の混雑時は長く待っても救えないため、
# 短リトライ1回だけで諦めてフォールバックに切り替える設計。
# 単発の瞬断（TCPレベル）は 1.5秒で拾えるケースが多い。
_RETRY_DELAYS_SERVER_BUSY = (1.5,)
_RETRY_DELAYS_TRANSIENT = (1.5,)
_SERVER_BUSY_STATUS = frozenset({500, 502, 503, 504})
_RATE_LIMIT_STATUS = 429
# ジッターは ±50%（thundering herd を確実に避けるため広めに取る）
_JITTER_RATIO = 0.5
# リトライ全体の累積予算（秒）。フォールバック呼び出しを含めた最大遅延を見込む
_TOTAL_RETRY_BUDGET_SEC = 30.0


def _apply_jitter(delay: float) -> float:
    """バックオフに±30%のジッターを適用する（雷鳴突進現象を回避）。"""
    return delay * (1.0 + random.uniform(-_JITTER_RATIO, _JITTER_RATIO))


def _parse_retry_after(response: Optional["requests.Response"]) -> Optional[float]:
    """Retry-After ヘッダーを秒数として返す。未指定・不正なら None。"""
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _execute_with_retry(
    request_fn: Callable[[], "requests.Response"],
    *,
    api_label: str,
    on_retry: Optional[Callable[[dict], None]] = None,
    disable_retry: bool = False,
) -> "requests.Response":
    """HTTP リクエストを指数バックオフでリトライする。

    - 500/502/503/504 → server_busy 扱い（1.5s ±50%）
    - 429 → サーバーから Retry-After があればそれを優先
    - ConnectionError / Timeout → transient 扱い（1.5s ±50%）
    - それ以外のステータスコードはそのまま response を返す（呼び出し側で処理）
    - 累積 _TOTAL_RETRY_BUDGET_SEC を超えそうならリトライ打ち切り

    on_retry: リトライ決定時（sleep 直前）に呼ばれるコールバック。
        引数 dict: {attempt, max, delay, status}
        UI の「再試行中 (n/n)」表示に利用する。
    disable_retry: True のときリトライせず初回の結果をそのまま返す。
        Fallback モデル呼び出しなど、上位がフォールバックチェーンを
        管理する場合に使う。
    """
    start = time.monotonic()
    max_retries = len(_RETRY_DELAYS_SERVER_BUSY)
    attempt = 0
    last_exception: Optional[BaseException] = None
    last_response: Optional["requests.Response"] = None

    while True:
        category: Optional[str] = None
        try:
            response = request_fn()
            last_exception = None
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exception = e
            last_response = None
            category = "transient"
            response = None

        if response is not None:
            if response.status_code in _SERVER_BUSY_STATUS:
                last_response = response
                category = "busy"
            elif response.status_code == _RATE_LIMIT_STATUS:
                last_response = response
                category = "rate_limit"
            else:
                return response  # 成功 or リトライ対象外のエラー

        if disable_retry:
            # リトライせず初回結果を返す（Fallback 呼び出し時など）
            break

        attempt += 1
        if attempt > max_retries:
            break

        if category == "transient":
            base_delay = _RETRY_DELAYS_TRANSIENT[attempt - 1]
        else:
            base_delay = _RETRY_DELAYS_SERVER_BUSY[attempt - 1]

        retry_after = _parse_retry_after(last_response)
        delay = retry_after if retry_after is not None else _apply_jitter(base_delay)

        elapsed = time.monotonic() - start
        if elapsed + delay > _TOTAL_RETRY_BUDGET_SEC:
            logger.warning(
                f"{api_label} リトライ予算({_TOTAL_RETRY_BUDGET_SEC:.0f}s)超過、"
                f"諦める (経過{elapsed:.1f}s + 待機{delay:.1f}s)"
            )
            break

        status_str = (
            str(last_response.status_code) if last_response is not None
            else type(last_exception).__name__
        )
        logger.info(
            f"{api_label} 一時エラー({status_str})、"
            f"{delay:.1f}秒後に再試行 ({attempt}/{max_retries})"
        )
        if on_retry is not None:
            try:
                on_retry({
                    "attempt": attempt,
                    "max": max_retries,
                    "delay": delay,
                    "status": status_str,
                })
            except Exception as cb_err:
                logger.debug(f"on_retry callback failed: {cb_err}")
        time.sleep(delay)

    # リトライ使い切り: 最後の例外を投げるか、最終レスポンスを返す
    if last_exception is not None:
        raise last_exception
    return last_response  # 呼び出し側で status_code をチェックしてエラーに変換


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
        on_retry: Optional[Callable[[dict], None]] = None,
        disable_retry: bool = False,
    ) -> str:
        """LLM APIを呼び出す。Geminiの場合はネイティブAPIを使用。

        Raises:
            ConfigurationError: base_url/model未設定
            ApiKeyError: APIキー不正
            NetworkError: ネットワークエラー
            RateLimitError: レート制限

        on_retry: リトライ発生時のコールバック（UI表示用）。
        disable_retry: True なら short リトライもスキップ。Fallback 呼び出し等。
        """
        if not self._base_url or not self._model:
            raise ConfigurationError("LLMのbase_urlとmodelを設定してください")

        if self.is_gemini():
            return self._call_gemini_native(
                messages, temperature, response_format, max_tokens, timeout,
                on_retry=on_retry, disable_retry=disable_retry,
            )

        return self._call_openai_compatible(
            messages, temperature, response_format, max_tokens, timeout,
            on_retry=on_retry, disable_retry=disable_retry,
        )

    def _call_gemini_native(
        self, messages: list, temperature: float,
        response_format: dict, max_tokens: int, timeout: float,
        on_retry: Optional[Callable[[dict], None]] = None,
        disable_retry: bool = False,
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
            response = _execute_with_retry(
                lambda: requests.post(
                    url, headers=headers, json=payload, timeout=timeout,
                ),
                api_label=f"Gemini({self._model})",
                on_retry=on_retry,
                disable_retry=disable_retry,
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
        on_retry: Optional[Callable[[dict], None]] = None,
        disable_retry: bool = False,
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
            response = _execute_with_retry(
                lambda: requests.post(
                    url, headers=headers, json=payload, timeout=timeout,
                ),
                api_label=f"LLM({self._model})",
                on_retry=on_retry,
                disable_retry=disable_retry,
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

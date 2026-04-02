# providers/llm_translate.py
# OpenAI API互換のLLM翻訳プロバイダー
# Gemini Flash, GPT-4o-mini, DeepSeek, Ollama等に対応

import asyncio
import base64
import json
import logging
import re
from typing import Dict, List, Optional

import requests

from .base import TranslationProvider, ProviderType, TextRegion, NetworkError, ApiKeyError

logger = logging.getLogger(__name__)

# ベースのシステムプロンプト（常に使用、言語指定を含む）
# OCR由来のテキストであることを明示し、エラー修正・略語保護・UIラベル対応を指示
BASE_SYSTEM_PROMPT = (
    "You are a game text translator. "
    "The input text was captured from a game screen via OCR and may contain "
    "recognition errors, broken words, or artifacts. "
    "Translate from {source_lang} to {target_lang}. "
    "Correct obvious OCR errors based on context, but do NOT add information "
    "that is not present in the original. "
    "Keep game-specific abbreviations (HP, MP, EXP, ATK, DEF, etc.), "
    "numbers, and proper nouns unchanged unless you know the standard "
    "localized form in {target_lang}. "
    "If the input is a short UI label or menu item, translate it concisely "
    "as a UI element. "
    "Return ONLY the translation. No explanations, notes, or extra text."
)

# デフォルトのシステムプロンプト（カスタムプロンプト未設定時のフルプロンプト）
DEFAULT_SYSTEM_PROMPT = BASE_SYSTEM_PROMPT


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
        parallel: bool = True,
    ):
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._api_key = api_key
        self._model = model
        self._custom_prompt = system_prompt  # ユーザーのグローバル追加指示（空なら使わない）
        self._game_prompt = ""  # ゲーム別プロンプト（空なら使わない）
        self._disable_thinking = disable_thinking
        self._parallel = parallel
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
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        system_prompt: str = None,
        game_prompt: str = None,
        disable_thinking: bool = None,
        parallel: bool = None,
    ) -> None:
        """設定を更新する。Noneでない値のみ更新（空文字列での明示的クリアに対応）。"""
        if base_url is not None:
            self._base_url = base_url.rstrip("/") if base_url else ""
        if api_key is not None:
            self._api_key = api_key
        if model is not None:
            self._model = model
        if system_prompt is not None:
            self._custom_prompt = system_prompt
        if game_prompt is not None:
            self._game_prompt = game_prompt
        if disable_thinking is not None:
            self._disable_thinking = disable_thinking
        if parallel is not None:
            self._parallel = parallel

    def _get_language_name(self, lang_code: str) -> str:
        """言語コードを自然言語名に変換する。"""
        return self.LANGUAGE_NAMES.get(lang_code, lang_code)

    def _build_system_prompt(self, source_lang: str, target_lang: str) -> str:
        """翻訳用のシステムプロンプトを構築する。

        ベースプロンプト（言語指定含む）は常に使用し、
        グローバルカスタムプロンプトとゲーム別プロンプトがあれば追加指示として付加する。
        両方が設定されている場合は両方を合成する（上書きではない）。
        """
        tgt_name = self._get_language_name(target_lang)
        if source_lang == "auto":
            src_name = "the detected language"
        else:
            src_name = self._get_language_name(source_lang)
        base = BASE_SYSTEM_PROMPT.format(
            source_lang=src_name, target_lang=tgt_name
        )
        # グローバル + ゲーム別プロンプトを合成
        additional = []
        if self._custom_prompt:
            additional.append(self._custom_prompt)
        if self._game_prompt:
            additional.append(self._game_prompt)
        if additional:
            return f"{base}\n\nAdditional instructions: {chr(10).join(additional)}"
        return base

    def _is_gemini(self) -> bool:
        """GeminiネイティブAPIを使うべきか判定する。
        モデル名がgemini-で始まり、かつbase_urlがGoogleのネイティブAPIの場合のみ。
        OpenRouter/LiteLLM等のプロキシ経由の場合はOpenAI互換APIを使う。"""
        return (
            self._model.strip().lower().startswith("gemini-")
            and "generativelanguage.googleapis.com" in self._base_url
        )

    def _call_api(
        self, messages: list, temperature: float = 0.1,
        response_format: dict = None,
        max_tokens: int = None,
        timeout: float = 30.0,
    ) -> str:
        """LLM APIを呼び出す。Geminiの場合はネイティブAPIを使用。"""
        if not self._base_url or not self._model:
            raise ApiKeyError("LLM base_url and model must be configured")

        # Gemini ネイティブAPI: thinkingConfig対応
        if self._is_gemini():
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
        # base_urlからネイティブAPIエンドポイントを構築
        # 例: https://generativelanguage.googleapis.com/v1beta/openai
        #   → https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
        base = self._base_url
        # /openai や /chat/completions を除去してベースを取得
        for suffix in ["/openai", "/chat/completions", "/v1"]:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
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

            # user/assistant → Gemini parts
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
                            # data:image/png;base64,xxx → inlineData
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
            # responseSchemaが指定されていればJSON構造を厳密に強制
            schema = response_format.get("schema")
            if schema:
                payload["generationConfig"]["responseSchema"] = schema

        # thinkingモード無効化
        if self._disable_thinking:
            payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}

        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout,
            )

            if response.status_code == 401 or response.status_code == 403:
                raise ApiKeyError("Invalid API key")
            if response.status_code == 429:
                from .base import RateLimitError
                raise RateLimitError("Rate limit exceeded")
            if response.status_code != 200:
                logger.warning(
                    f"Gemini API error: {response.status_code} - {response.text[:300]}"
                )
                raise NetworkError(f"Gemini API returned status {response.status_code}")

            result = response.json()
            candidate = result["candidates"][0]
            finish_reason = candidate.get("finishReason", "unknown")
            content = candidate["content"]["parts"][0]["text"]

            if finish_reason not in ("STOP", "stop"):
                logger.warning(
                    f"Gemini finish_reason={finish_reason} "
                    f"(content length={len(content)})"
                )

            content = self._strip_thinking_tags(content)
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
            # OpenAI互換APIに渡す形式に変換（内部のschemaキーを除去）
            fmt = {k: v for k, v in response_format.items() if k != "schema"}
            # schemaがある場合はjson_schema形式に変換（GPT-4o等が対応）
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

        # thinkingモード無効化: Ollama/DashScope/vLLM等の緩いサーバーのみに送信
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
                from .base import RateLimitError
                raise RateLimitError("Rate limit exceeded")
            if response.status_code != 200:
                logger.warning(
                    f"LLM API error: {response.status_code} - {response.text[:200]}"
                )
                raise NetworkError(f"LLM API returned status {response.status_code}")

            result = response.json()
            choice = result["choices"][0]
            finish_reason = choice.get("finish_reason", "unknown")
            content = choice["message"]["content"]
            if finish_reason != "stop":
                logger.warning(
                    f"LLM finish_reason={finish_reason} "
                    f"(content length={len(content)})"
                )
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

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if not text or not text.strip():
            return text

        system_prompt = self._build_system_prompt(source_lang, target_lang)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
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
            f"Translate the following {len(texts)} texts extracted from the same game screen. "
            "Each line is numbered with [N]. "
            "Return ONLY the translations, one per line, with the same [N] numbering. "
            "Do NOT add any extra text or explanations."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{batch_instruction}\n\n{user_content}"},
        ]

        logger.debug(
            f"LLM batch translate: {len(texts)} texts, "
            f"{source_lang} -> {target_lang}"
        )

        try:
            result = await asyncio.to_thread(self._call_api, messages)
            translated = self._parse_batch_response(result, len(texts))

            # 欠落している翻訳を特定
            missing_indices = [i for i, t in enumerate(translated) if t is None]

            if not missing_indices:
                return translated

            # 欠落分だけ個別翻訳で補完
            logger.warning(
                f"LLM batch: {len(missing_indices)}/{len(texts)} translations missing "
                f"(indices: {missing_indices}), fetching individually"
            )
            for i in missing_indices:
                try:
                    translated[i] = await self.translate(
                        texts[i], source_lang, target_lang
                    )
                except Exception as e:
                    logger.warning(f"Individual translation failed for [{i+1}]: {e}")
                    translated[i] = texts[i]  # 原文をそのまま返す

            return translated

        except Exception as e:
            logger.error(f"LLM batch translation error: {e}")
            # エラー時は個別翻訳にフォールバック
            return await self._translate_individually(texts, source_lang, target_lang)

    # バッチレスポンスの [N] 番号を厳密にマッチする正規表現
    _NUM_PREFIX_RE = re.compile(r"^\[(\d+)\]\s*(.*)")

    def _parse_batch_response(self, response: str, expected_count: int) -> List[str]:
        """バッチレスポンスをパースして翻訳テキストのリストを返す。

        [N] 番号を使って正しい位置にマッピングする。
        番号なしの行は直前の番号の続き（LLMが改行で分割した場合）として結合する。
        番号が欠落している場合はNoneを返す。
        """
        lines = response.strip().split("\n")
        result_map: dict = {}
        current_num = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            match = self._NUM_PREFIX_RE.match(line)
            if match:
                num = int(match.group(1))
                text = match.group(2)
                if 1 <= num <= expected_count:
                    current_num = num
                    result_map[num] = text
                # 範囲外の番号は無視
            elif current_num is not None:
                # 番号なし行: 直前の翻訳の続き（LLMが改行で分割した場合）
                result_map[current_num] += " " + line

        # 連番で結果を組み立て（欠落はNone）
        return [result_map.get(i) for i in range(1, expected_count + 1)]

    async def _translate_individually(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        """個別に翻訳する（フォールバック用）。並列設定に応じて逐次/並列を切り替え。"""
        if self._parallel:
            return await self._translate_individually_parallel(
                texts, source_lang, target_lang
            )
        results = []
        for text in texts:
            try:
                translated = await self.translate(text, source_lang, target_lang)
                results.append(translated)
            except Exception as e:
                logger.warning(f"Individual translation failed: {e}")
                results.append(text)
        return results

    async def _translate_individually_parallel(
        self, texts: List[str], source_lang: str, target_lang: str
    ) -> List[str]:
        """個別翻訳を並列実行する。"""
        async def _one(text: str) -> str:
            try:
                return await self.translate(text, source_lang, target_lang)
            except Exception as e:
                logger.warning(f"Individual translation failed: {e}")
                return text

        return list(await asyncio.gather(*[_one(t) for t in texts]))

    async def translate_with_image(
        self,
        ocr_text: str,
        image_base64: str,
        confidence: float,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """画像付きでLLMに翻訳を依頼する。

        OCR信頼度が低いテキスト領域の切り出し画像を送り、
        LLMにOCR再認識+翻訳を一括で行わせる。
        OpenAI API互換のVision機能（content配列にimage_url型）を使用。

        Args:
            ocr_text: OCRが認識したテキスト（参考情報）
            image_base64: 切り出し画像のBase64文字列（PNG/JPEG）
            confidence: OCRの信頼度スコア（0.0-1.0）
            source_lang: ソース言語コード
            target_lang: ターゲット言語コード

        Returns:
            翻訳済みテキスト
        """
        tgt_name = self._get_language_name(target_lang)
        if source_lang == "auto":
            src_name = "the detected language"
        else:
            src_name = self._get_language_name(source_lang)

        confidence_pct = int(confidence * 100)

        system_prompt = (
            "You are a game text translator with OCR capability. "
            "You will receive a cropped image from a game screen along with "
            "an OCR engine's attempt at reading it. "
            "The OCR result may be inaccurate. "
            "Read the text directly from the image, then translate it "
            f"from {src_name} to {tgt_name}. "
            "Keep game-specific abbreviations (HP, MP, EXP, ATK, DEF, etc.), "
            "numbers, and proper nouns unchanged unless you know the standard "
            f"localized form in {tgt_name}. "
            "Return ONLY the translation. No explanations, notes, or extra text."
        )
        # グローバル + ゲーム別プロンプトを合成
        additional = []
        if self._custom_prompt:
            additional.append(self._custom_prompt)
        if self._game_prompt:
            additional.append(self._game_prompt)
        if additional:
            system_prompt += f"\n\nAdditional instructions: {chr(10).join(additional)}"

        # image_base64がdata URIでない場合は付与
        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"

        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": image_base64},
            },
            {
                "type": "text",
                "text": (
                    f"OCR result (confidence: {confidence_pct}%): \"{ocr_text}\"\n"
                    "Please read the text from the image and translate it."
                ),
            },
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.debug(
            f"LLM image translate: confidence={confidence_pct}%, "
            f"ocr_text='{ocr_text}', {source_lang} -> {target_lang}"
        )
        result = await asyncio.to_thread(self._call_api, messages)
        return result

    # --- Vision Translation: OCRバイパス、画像から直接テキスト検出+翻訳 ---

    @staticmethod
    def _extract_json(text: str):
        """LLMレスポンスからJSONオブジェクトまたは配列を抽出する。
        マークダウンコードブロックやゴミテキストに対応。"""
        # thinkingタグ除去
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
        # マークダウンコードブロック除去
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        # まず直接パースを試す
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.debug(f"_extract_json: 直接パース失敗: {e}")
        # 最初の { または [ から対応する閉じ括弧までを抽出して再パース
        for open_ch, close_ch in [('{', '}'), ('[', ']')]:
            start = text.find(open_ch)
            end = text.rfind(close_ch)
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError as e:
                    logger.debug(
                        f"_extract_json: {open_ch}..{close_ch} パース失敗: {e}, "
                        f"range={start}..{end+1}/{len(text)}"
                    )
                    continue
        raise json.JSONDecodeError("No JSON object found", text, 0)

    @staticmethod
    def _recover_truncated_json(text: str):
        """途切れたJSONから有効なregionを部分回復する。

        finish_reason=lengthでJSONが途中で切れた場合、最後の完全なオブジェクトまでを
        抽出してパースする。回復不能ならNoneを返す。
        """
        # thinkingタグ・コードブロック除去
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()

        # "regions" 配列の中身を探して、最後の完全な },{ 区切りまでを使う
        # 配列直返しの場合は先頭の [ から
        for attempt in range(3):
            # 最後の完全な "}," or "}" を探してそこで切る
            last_complete = text.rfind('},')
            last_single = text.rfind('}')
            if last_complete > 0:
                truncated = text[:last_complete + 1]  # }, の } まで
            elif last_single > 0:
                truncated = text[:last_single + 1]
            else:
                return None

            # 開き括弧を補完
            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            truncated += '}' * max(0, open_braces)
            truncated += ']' * max(0, open_brackets)

            try:
                parsed = json.loads(truncated)
                region_count = 0
                if isinstance(parsed, list):
                    region_count = len(parsed)
                elif isinstance(parsed, dict):
                    region_count = len(parsed.get("regions", []))
                logger.info(f"Vision 部分回復成功: {region_count} regions recovered")
                return parsed
            except json.JSONDecodeError:
                # さらに手前で切って再試行
                text = text[:last_complete] if last_complete > 0 else text[:last_single]
                continue

        return None

    @staticmethod
    def _generate_test_png_base64() -> str:
        """preflight用の最小テスト画像（1x1白PNG）をBase64で生成する。
        PIL不要。PNG仕様に基づきzlibで手組み。"""
        import struct
        import zlib

        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        # 1x1 白ピクセル、RGB
        width, height = 1, 1
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
        raw_row = b"\x00\xff\xff\xff"  # filter=None, R=255, G=255, B=255
        idat = zlib.compress(raw_row)

        png = b"\x89PNG\r\n\x1a\n"
        png += _chunk(b"IHDR", ihdr)
        png += _chunk(b"IDAT", idat)
        png += _chunk(b"IEND", b"")
        return base64.b64encode(png).decode()

    def preflight_vision_check(self) -> tuple:
        """Vision + JSON構造化出力の対応を検証する。同期メソッド。

        Returns:
            (success: bool, error_message: str)
        """
        if not self._base_url or not self._model:
            return (False, "LLM base_url and model must be configured")

        test_image_b64 = self._generate_test_png_base64()
        data_uri = f"data:image/png;base64,{test_image_b64}"

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an image analyzer. Return valid JSON only. "
                    "Analyze the image and return any text you find."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {
                        "type": "text",
                        "text": (
                            'Return JSON: {"regions": [{"text": "detected text", '
                            '"rect": {"left": 0, "top": 0, "right": 1, "bottom": 1}}]}. '
                            "If no text found, return {\"regions\": []}."
                        ),
                    },
                ],
            },
        ]

        try:
            result = self._call_api(
                messages, temperature=0.0,
                response_format={"type": "json_object"},
            )
            # JSONパース可能であればVision+JSON構造化出力に対応
            self._extract_json(result)
            logger.info("Vision preflight成功: Vision + JSON対応確認")
            return (True, "")

        except json.JSONDecodeError as e:
            msg = f"モデルがJSON構造化出力に対応していません: {e}"
            logger.warning(f"Vision preflight失敗: {msg}")
            return (False, msg)
        except ApiKeyError as e:
            return (False, str(e))
        except NetworkError as e:
            return (False, str(e))
        except Exception as e:
            msg = f"Vision preflight失敗: {e}"
            logger.warning(msg)
            return (False, msg)

    async def recognize_and_translate(
        self,
        image_base64: str,
        source_lang: str,
        target_lang: str,
        image_width: int,
        image_height: int,
    ) -> List[dict]:
        """スクリーンショットから直接テキスト検出+翻訳を行う（OCRバイパス）。

        Vision APIでフルスクリーンショットを送り、テキスト領域の座標と翻訳を
        JSON構造化出力で1回のAPIコールで取得する。

        Args:
            image_base64: フルスクリーンショットのBase64文字列
            source_lang: ソース言語コード
            target_lang: ターゲット言語コード
            image_width: 画像の幅（ピクセル）
            image_height: 画像の高さ（ピクセル）

        Returns:
            領域リスト: [{"text": str, "translated_text": str, "rect": {...}}]

        Raises:
            Exception: JSONパース失敗、API呼び出し失敗等
        """
        tgt_name = self._get_language_name(target_lang)
        if source_lang == "auto":
            src_name = "the detected language"
        else:
            src_name = self._get_language_name(source_lang)

        system_prompt = (
            "You are a game screen text detector and translator. "
            "You will receive a game screenshot. "
            f"Find all text, translate from {src_name} to {tgt_name}. "
            "Keep abbreviations (HP, MP, EXP, etc.) and proper nouns unchanged. "
            "Group text by semantic meaning: merge consecutive lines that form a paragraph or sentence into ONE region. "
            "Menu items, buttons, labels, and standalone UI elements must each be a SEPARATE region. "
            "The rect must cover the entire grouped text area. "
            "Use normalized coordinates 0-1000 for rect (0=top-left, 1000=bottom-right). "
            "Return JSON only."
        )
        # グローバル + ゲーム別プロンプトを合成
        additional = []
        if self._custom_prompt:
            additional.append(self._custom_prompt)
        if self._game_prompt:
            additional.append(self._game_prompt)
        if additional:
            system_prompt += f"\n\n{chr(10).join(additional)}"

        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"

        user_content = [
            {"type": "image_url", "image_url": {"url": image_base64}},
            {
                "type": "text",
                "text": (
                    "Return compact single-line JSON (no newlines, no indentation):\n"
                    '{"coordinate_mode":"normalized_0_1000","regions":[{"text":"original",'
                    '"translated_text":"翻訳",'
                    '"rect":{"left":0,"top":0,"right":500,"bottom":250}}]}\n'
                    "Rect values are 0-1000 normalized (0=top-left, 1000=bottom-right)."
                ),
            },
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(
            f"Vision recognize_and_translate: {image_width}x{image_height}, "
            f"{source_lang} -> {target_lang}"
        )

        # JSON構造を厳密に強制するスキーマ
        # Gemini: responseSchema、OpenAI互換: json_schema として使用
        vision_schema = {
            "type": "object",
            "properties": {
                "coordinate_mode": {
                    "type": "string",
                    "enum": ["pixel", "normalized_0_1000"],
                },
                "regions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "translated_text": {"type": "string"},
                            "rect": {
                                "type": "object",
                                "properties": {
                                    "left": {"type": "integer"},
                                    "top": {"type": "integer"},
                                    "right": {"type": "integer"},
                                    "bottom": {"type": "integer"},
                                },
                                "required": ["left", "top", "right", "bottom"],
                            },
                        },
                        "required": ["text", "translated_text", "rect"],
                    },
                },
            },
            "required": ["coordinate_mode", "regions"],
        }

        result = await asyncio.to_thread(
            self._call_api, messages,
            response_format={"type": "json_object", "schema": vision_schema},
            max_tokens=8192,
            timeout=60.0,
        )
        logger.info(f"Vision output ({len(result)} chars): {result[:500]!r}")

        try:
            parsed = self._extract_json(result)
        except json.JSONDecodeError as e:
            # パース失敗 → 途切れたJSONの部分回復を試みる
            logger.warning(
                f"Vision JSONパースエラー: {e} — 部分回復を試行"
            )
            parsed = self._recover_truncated_json(result)
            if parsed is None:
                logger.error(f"Vision 部分回復も失敗。フルレスポンス ({len(result)} chars):\n{result}")
                raise

        # LLMが {"regions": [...]} または直接 [...] を返す場合の両方に対応
        # coordinate_modeの自己申告を読み取る
        reported_coordinate_mode = None
        if isinstance(parsed, list):
            regions = parsed
        elif isinstance(parsed, dict):
            regions = parsed.get("regions", [])
            reported_coordinate_mode = parsed.get("coordinate_mode")
        else:
            raise ValueError(f"Invalid response type: {type(parsed)}")

        if not isinstance(regions, list):
            raise ValueError(f"Invalid response: 'regions' is not a list: {type(regions)}")

        # 有効な領域のみフィルタ
        valid_regions = []
        for r in regions:
            if not isinstance(r, dict):
                continue
            text = r.get("text", "")
            translated = r.get("translated_text", "")
            rect = r.get("rect")
            if not text or not rect or not isinstance(rect, dict):
                continue
            # 必須フィールドの存在チェック
            if not all(k in rect for k in ("left", "top", "right", "bottom")):
                continue
            valid_regions.append({
                "text": str(text),
                "translated_text": str(translated or text),
                "rect": {
                    "left": int(rect["left"]),
                    "top": int(rect["top"]),
                    "right": int(rect["right"]),
                    "bottom": int(rect["bottom"]),
                },
            })

        logger.info(
            f"Vision: {len(valid_regions)}/{len(regions)} valid regions, "
            f"reported_coordinate_mode={reported_coordinate_mode}"
        )
        return valid_regions, reported_coordinate_mode

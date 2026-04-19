# providers/gemini_vision.py
# Vision翻訳プロバイダー（Gemini / OpenAI互換Vision API対応）
# OCR補助（assist）とOCRバイパス（direct）の両方を実装

import asyncio
import base64
import json
import logging
import re
import struct
import zlib
from typing import List, Optional

from .vision_base import VisionProvider
from .llm_api_client import LlmApiClient
from .base import ApiKeyError, NetworkError

logger = logging.getLogger(__name__)

# 言語コードから自然言語名へのマッピング
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


def _get_language_name(lang_code: str) -> str:
    """言語コードを自然言語名に変換する。"""
    return LANGUAGE_NAMES.get(lang_code, lang_code)


class GeminiVisionProvider(VisionProvider):
    """Vision翻訳プロバイダー。Gemini ネイティブAPI / OpenAI互換Vision APIに対応。

    LlmApiClientをコンポジションで保持し、Vision固有のプロンプト構築・
    JSONパース・座標処理を担当する。
    """

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        model: str = "",
        disable_thinking: bool = True,
        custom_prompt: str = "",
        game_prompt: str = "",
    ):
        self._client = LlmApiClient(
            base_url=base_url,
            api_key=api_key,
            model=model,
            disable_thinking=disable_thinking,
        )
        self._custom_prompt = custom_prompt
        self._game_prompt = game_prompt

    @property
    def name(self) -> str:
        return f"Vision ({self._client.model or 'unconfigured'})"

    def configure(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        disable_thinking: bool = None,
        custom_prompt: str = None,
        game_prompt: str = None,
    ) -> None:
        """設定を更新する。Noneでない値のみ更新。"""
        self._client.configure(
            base_url=base_url,
            api_key=api_key,
            model=model,
            disable_thinking=disable_thinking,
        )
        if custom_prompt is not None:
            self._custom_prompt = custom_prompt
        if game_prompt is not None:
            self._game_prompt = game_prompt

    def is_available(self) -> bool:
        return self._client.is_configured()

    def _build_additional_prompt(self) -> str:
        """共通Vision プロンプト + ゲーム別Vision プロンプトの追加指示を合成する。
        注入順: 共通Vision プロンプト → ゲーム別Vision プロンプト"""
        additional = []
        if self._custom_prompt:
            additional.append(self._custom_prompt)
        if self._game_prompt:
            additional.append(self._game_prompt)
        if additional:
            return f"\n\nAdditional instructions:\n{chr(10).join(additional)}"
        return ""

    # --- assist モード: OCR低信頼度領域の画像付き再認識+翻訳 ---
    # 注入順: Vision Assist固定プロンプト → 共通Vision プロンプト → ゲーム別Vision プロンプト

    async def assist_translate(
        self,
        ocr_text: str,
        image_base64: str,
        confidence: float,
        source_lang: str,
        target_lang: str,
    ) -> str:
        tgt_name = _get_language_name(target_lang)
        src_name = "the detected language" if source_lang == "auto" else _get_language_name(source_lang)

        confidence_pct = int(confidence * 100)

        # Vision Assist固定プロンプト: 役割定義・出力契約・hallucination抑制のみ
        system_prompt = (
            "You are a game text translator with OCR capability. "
            "You will receive a cropped image from a game screen along with "
            "an OCR engine's attempt at reading it. "
            "The OCR result may be inaccurate. "
            "Read the text directly from the image, then translate it "
            f"from {src_name} to {tgt_name}. "
            "Do NOT add information that is not present in the original. "
            "Return ONLY the translation. No explanations, notes, or extra text."
        )
        system_prompt += self._build_additional_prompt()

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
            f"Vision assist: confidence={confidence_pct}%, "
            f"ocr_text='{ocr_text}', {source_lang} -> {target_lang}"
        )
        result = await asyncio.to_thread(self._client.call, messages)
        return result

    # --- direct モード: OCRバイパス、画像から直接テキスト検出+翻訳 ---
    # 注入順: Vision Direct固定プロンプト → 共通Vision プロンプト → ゲーム別Vision プロンプト

    async def direct_translate(
        self,
        image_base64: str,
        source_lang: str,
        target_lang: str,
        image_width: int,
        image_height: int,
        on_retry=None,
        disable_retry: bool = False,
    ) -> tuple:
        tgt_name = _get_language_name(target_lang)
        src_name = "the detected language" if source_lang == "auto" else _get_language_name(source_lang)

        # Vision Direct固定プロンプト: 役割定義・出力契約・JSON schema契約のみ
        # テキストのグルーピング方針等は共通/ゲーム別Visionプロンプト（vision-common.txt）に入れる
        system_prompt = (
            "You are a game screen text detector and translator. "
            "You will receive a game screenshot. "
            f"Find all text, translate from {src_name} to {tgt_name}. "
            "Do NOT add information that is not present in the original. "
            "The rect must cover the entire text area for each region. "
            "Use normalized coordinates 0-1000 for rect (0=top-left, 1000=bottom-right). "
            "Return JSON only."
        )
        system_prompt += self._build_additional_prompt()

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
            f"Vision direct: {image_width}x{image_height}, "
            f"{source_lang} -> {target_lang}"
        )

        # JSON構造を厳密に強制するスキーマ
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
            self._client.call, messages,
            response_format={"type": "json_object", "schema": vision_schema},
            max_tokens=8192,
            timeout=60.0,
            on_retry=on_retry,
            disable_retry=disable_retry,
        )
        logger.info(f"Vision output ({len(result)} chars): {result[:500]!r}")

        try:
            parsed = self._extract_json(result)
        except json.JSONDecodeError as e:
            logger.warning(
                f"Vision JSONパースエラー: {e} — 部分回復を試行"
            )
            parsed = self._recover_truncated_json(result)
            if parsed is None:
                logger.error(f"Vision 部分回復も失敗。フルレスポンス ({len(result)} chars):\n{result}")
                raise

        # LLMが {"regions": [...]} または直接 [...] を返す場合の両方に対応
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
            f"Vision direct: {len(valid_regions)}/{len(regions)} valid regions, "
            f"reported_coordinate_mode={reported_coordinate_mode}"
        )
        return valid_regions, reported_coordinate_mode

    # --- describe モード: 攻略支援向け画面説明 ---

    async def describe_screen(
        self,
        image_base64: str,
        image_width: int,
        image_height: int,
        prompt: str = None,
    ) -> dict:
        """ゲーム画面を攻略支援向けに構造化して説明する。

        Returns:
            {"summary": str, "objectives": [...], "ui": [...], "notable_text": [...]}
        """
        # 画面説明固定プロンプト
        system_prompt = (
            "You are a game screen analyzer for gameplay assistance. "
            "You will receive a game screenshot. "
            "Analyze the screen and return a structured JSON summary. "
            "Do NOT guess or hallucinate — only report what is visibly present. "
            "If something is unclear, say so. "
            "Return JSON only, in Japanese."
        )

        # 共通/ゲーム別プロンプトを追加（翻訳経路と同じ設定を反映）
        system_prompt += self._build_additional_prompt()

        # ユーザー指定のカスタムプロンプトがあれば追加
        if prompt:
            system_prompt += f"\n\nAdditional user instructions:\n{prompt}"

        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/png;base64,{image_base64}"

        user_content = [
            {"type": "image_url", "image_url": {"url": image_base64}},
            {
                "type": "text",
                "text": (
                    "Analyze this game screen for gameplay assistance. "
                    "Return compact single-line JSON (no newlines, no indentation):\n"
                    '{"summary":"画面の簡潔な要約",'
                    '"objectives":["次の目的や目標"],'
                    '"ui":["HP 100/200","MP 50/80"],'
                    '"notable_text":["重要な会話やテキスト"]}\n'
                    "Only include fields that have visible content. "
                    "Empty arrays are fine for fields with no relevant content."
                ),
            },
        ]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        logger.info(f"describe_screen: {image_width}x{image_height}")

        describe_schema = {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "objectives": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "ui": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "notable_text": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["summary"],
        }

        result = await asyncio.to_thread(
            self._client.call, messages,
            response_format={"type": "json_object", "schema": describe_schema},
            max_tokens=4096,
            timeout=60.0,
        )
        logger.info(f"describe_screen output ({len(result)} chars): {result[:300]!r}")

        parsed = self._extract_json(result)

        # 必須フィールドの正規化
        if not isinstance(parsed, dict):
            raise ValueError(f"describe_screen: 不正なレスポンス型: {type(parsed)}")

        return {
            "summary": str(parsed.get("summary", "")),
            "objectives": [str(o) for o in parsed.get("objectives", []) if o],
            "ui": [str(u) for u in parsed.get("ui", []) if u],
            "notable_text": [str(t) for t in parsed.get("notable_text", []) if t],
        }

    # --- preflight ---
    # 固定プロンプトのみ使用。共通/ゲーム別プロンプトは注入しない。

    async def preflight_check(self) -> tuple:
        if not self._client.is_configured():
            return (False, "Vision用のbase_urlとmodelを設定してください")

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

        # direct_translate() と同じ形式で検証する
        # json_object だけ通っても json_schema が非対応なら本番で失敗する
        preflight_schema = {
            "type": "object",
            "properties": {
                "regions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
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
                        "required": ["text", "rect"],
                    },
                },
            },
            "required": ["regions"],
        }

        try:
            result = await asyncio.to_thread(
                self._client.call, messages,
                temperature=0.0,
                response_format={"type": "json_object", "schema": preflight_schema},
            )
            self._extract_json(result)
            logger.info("Vision preflight成功: Vision + JSON Schema対応確認")
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

    # --- JSONパース・回復ユーティリティ ---

    @staticmethod
    def _extract_json(text: str):
        """LLMレスポンスからJSONオブジェクトまたは配列を抽出する。"""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<reasoning>.*?</reasoning>", "", text, flags=re.DOTALL)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.debug(f"_extract_json: 直接パース失敗: {e}")
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
        """途切れたJSONから有効なregionを部分回復する。"""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r'```json\s*', '', text)
        text = re.sub(r'```\s*', '', text)
        text = text.strip()

        for attempt in range(3):
            last_complete = text.rfind('},')
            last_single = text.rfind('}')
            if last_complete > 0:
                truncated = text[:last_complete + 1]
            elif last_single > 0:
                truncated = text[:last_single + 1]
            else:
                return None

            open_braces = truncated.count('{') - truncated.count('}')
            open_brackets = truncated.count('[') - truncated.count(']')
            # 配列を先に閉じてからオブジェクトを閉じる（{"regions":[...]} のネスト順）
            truncated += ']' * max(0, open_brackets)
            truncated += '}' * max(0, open_braces)

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
                text = text[:last_complete] if last_complete > 0 else text[:last_single]
                continue

        return None

    @staticmethod
    def _generate_test_png_base64() -> str:
        """preflight用の最小テスト画像（1x1白PNG）をBase64で生成する。"""
        def _chunk(chunk_type: bytes, data: bytes) -> bytes:
            c = chunk_type + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        width, height = 1, 1
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        raw_row = b"\x00\xff\xff\xff"
        idat = zlib.compress(raw_row)

        png = b"\x89PNG\r\n\x1a\n"
        png += _chunk(b"IHDR", ihdr)
        png += _chunk(b"IDAT", idat)
        png += _chunk(b"IEND", b"")
        return base64.b64encode(png).decode()

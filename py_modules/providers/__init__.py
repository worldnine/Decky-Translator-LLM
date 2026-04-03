# providers/__init__.py
# Provider factory and manager

import asyncio
import base64
import io
import logging
import os
import subprocess
from typing import List, Optional

from .base import (
    OCRProvider,
    TranslationProvider,
    ProviderType,
    TextRegion,
    NetworkError,
    ApiKeyError,
    RateLimitError,
    ConfigurationError,
)
from .google_ocr import GoogleVisionProvider
from .google_translate import GoogleTranslateProvider
from .ocrspace import OCRSpaceProvider
from .free_translate import FreeTranslateProvider
from .rapidocr_provider import RapidOCRProvider
from .llm_translate import LlmTranslateProvider
from .vision_base import VisionProvider
from .gemini_vision import GeminiVisionProvider

logger = logging.getLogger(__name__)

# Export all public classes
__all__ = [
    'OCRProvider',
    'TranslationProvider',
    'VisionProvider',
    'ProviderType',
    'TextRegion',
    'NetworkError',
    'ApiKeyError',
    'RateLimitError',
    'ConfigurationError',
    'GoogleVisionProvider',
    'GoogleTranslateProvider',
    'OCRSpaceProvider',
    'FreeTranslateProvider',
    'RapidOCRProvider',
    'LlmTranslateProvider',
    'GeminiVisionProvider',
    'ProviderManager',
]


class ProviderManager:
    """Factory and manager for OCR, Translation, and Vision providers."""

    def __init__(self):
        """Initialize the provider manager."""
        # Provider instances (created on demand)
        self._ocr_providers = {}
        self._translation_providers = {}
        self._vision_provider: Optional[GeminiVisionProvider] = None

        # Configuration
        self._use_free_providers = True
        self._google_api_key = ""
        self._ocr_provider_preference = "rapidocr"
        self._translation_provider_preference = "freegoogle"
        self._rapidocr_confidence = 0.5
        self._rapidocr_box_thresh = 0.5
        self._rapidocr_unclip_ratio = 1.6

        # LLM翻訳プロバイダー設定（テキスト翻訳用）
        self._llm_base_url = ""
        self._llm_api_key = ""
        self._llm_model = ""
        self._llm_system_prompt = ""
        self._llm_game_prompt = ""
        self._llm_disable_thinking = True
        self._llm_parallel = True  # LLMテキスト翻訳のバッチ並列制御（Vision parallelとは独立）

        # Vision設定（OCR/Translation とは独立）
        self._vision_mode = "off"  # "off", "assist", "direct"
        self._vision_base_url = ""  # 空ならLLM設定をフォールバック
        self._vision_api_key = ""
        self._vision_model = ""
        self._vision_parallel = True
        self._vision_assist_confidence_threshold = 0.95
        self._vision_assist_send_all = False
        self._vision_coordinate_mode = "pixel"

        logger.debug("ProviderManager initialized")

    def configure_llm(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        system_prompt: str = None,
        game_prompt: str = None,
        disable_thinking: bool = None,
        parallel: bool = None,
    ) -> None:
        """LLM翻訳プロバイダーの設定を更新する（テキスト翻訳用）。"""
        if base_url is not None:
            self._llm_base_url = base_url
        if api_key is not None:
            self._llm_api_key = api_key
        if model is not None:
            self._llm_model = model
        if system_prompt is not None:
            self._llm_system_prompt = system_prompt
        if game_prompt is not None:
            self._llm_game_prompt = game_prompt
        if disable_thinking is not None:
            self._llm_disable_thinking = disable_thinking
        if parallel is not None:
            self._llm_parallel = parallel

        # 既存のLLMプロバイダーインスタンスがあれば更新
        llm_provider = self._translation_providers.get(ProviderType.LLM)
        if llm_provider:
            llm_provider.configure(
                base_url=base_url, api_key=api_key,
                model=model, system_prompt=system_prompt,
                game_prompt=game_prompt,
                disable_thinking=disable_thinking,
                parallel=parallel,
            )

        # Vision ProviderがLLM設定をフォールバックしている場合も更新
        if self._vision_provider:
            self._update_vision_provider_config()

        logger.debug(
            f"LLM config updated: base_url={self._llm_base_url}, "
            f"model={self._llm_model}, disable_thinking={self._llm_disable_thinking}"
        )

    def configure_vision(
        self,
        mode: str = None,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        parallel: bool = None,
        assist_send_all: bool = None,
        assist_confidence_threshold: float = None,
        coordinate_mode: str = None,
    ) -> None:
        """Vision設定を更新する。"""
        if mode is not None:
            self._vision_mode = mode
        if base_url is not None:
            self._vision_base_url = base_url
        if api_key is not None:
            self._vision_api_key = api_key
        if model is not None:
            self._vision_model = model
        if parallel is not None:
            self._vision_parallel = parallel
        if assist_send_all is not None:
            self._vision_assist_send_all = assist_send_all
        if assist_confidence_threshold is not None:
            self._vision_assist_confidence_threshold = assist_confidence_threshold
        if coordinate_mode is not None:
            self._vision_coordinate_mode = coordinate_mode

        # 既存のVision Providerがあれば更新
        if self._vision_provider:
            self._update_vision_provider_config()

        logger.debug(
            f"Vision config updated: mode={self._vision_mode}, "
            f"parallel={self._vision_parallel}, "
            f"assist_threshold={self._vision_assist_confidence_threshold}"
        )

    def _update_vision_provider_config(self) -> None:
        """Vision Providerの設定を現在の状態に合わせて更新する。
        Vision専用設定が空ならLLM設定をフォールバック。"""
        if not self._vision_provider:
            return
        self._vision_provider.configure(
            base_url=self._vision_base_url or self._llm_base_url,
            api_key=self._vision_api_key or self._llm_api_key,
            model=self._vision_model or self._llm_model,
            disable_thinking=self._llm_disable_thinking,
            custom_prompt=self._llm_system_prompt,
            game_prompt=self._llm_game_prompt,
        )

    def configure(
        self,
        use_free_providers: bool = True,
        google_api_key: str = "",
        ocr_provider: str = "",
        translation_provider: str = ""
    ) -> None:
        """Configure provider preferences."""
        self._google_api_key = google_api_key

        if ocr_provider:
            self._ocr_provider_preference = ocr_provider
            self._use_free_providers = (ocr_provider != "googlecloud")
        else:
            self._use_free_providers = use_free_providers
            self._ocr_provider_preference = "rapidocr" if use_free_providers else "googlecloud"

        if translation_provider:
            self._translation_provider_preference = translation_provider
        elif not translation_provider and ocr_provider:
            self._translation_provider_preference = "googlecloud" if ocr_provider == "googlecloud" else "freegoogle"
        elif not use_free_providers:
            self._translation_provider_preference = "googlecloud"

        if ProviderType.GOOGLE in self._ocr_providers:
            self._ocr_providers[ProviderType.GOOGLE].set_api_key(google_api_key)
        if ProviderType.GOOGLE in self._translation_providers:
            self._translation_providers[ProviderType.GOOGLE].set_api_key(google_api_key)

        logger.debug(
            f"Provider config updated: ocr_provider={self._ocr_provider_preference}, "
            f"translation_provider={self._translation_provider_preference}, "
            f"google_api_key_set={bool(google_api_key)}"
        )

    def set_rapidocr_confidence(self, confidence: float) -> None:
        self._rapidocr_confidence = confidence
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_min_confidence(confidence)
        logger.debug(f"RapidOCR confidence set to {confidence}")

    def set_rapidocr_box_thresh(self, box_thresh: float) -> None:
        self._rapidocr_box_thresh = box_thresh
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_box_thresh(box_thresh)
        logger.debug(f"RapidOCR box_thresh set to {box_thresh}")

    def set_rapidocr_unclip_ratio(self, unclip_ratio: float) -> None:
        self._rapidocr_unclip_ratio = unclip_ratio
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_unclip_ratio(unclip_ratio)
        logger.debug(f"RapidOCR unclip_ratio set to {unclip_ratio}")

    def get_ocr_provider(
        self, provider_type: Optional[ProviderType] = None
    ) -> Optional[OCRProvider]:
        if provider_type is None:
            if self._ocr_provider_preference == "rapidocr":
                provider_type = ProviderType.RAPIDOCR
            elif self._ocr_provider_preference == "ocrspace":
                provider_type = ProviderType.OCR_SPACE
            else:
                provider_type = ProviderType.GOOGLE

        if provider_type not in self._ocr_providers:
            if provider_type == ProviderType.RAPIDOCR:
                self._ocr_providers[provider_type] = RapidOCRProvider(
                    min_confidence=self._rapidocr_confidence
                )
            elif provider_type == ProviderType.OCR_SPACE:
                self._ocr_providers[provider_type] = OCRSpaceProvider()
            elif provider_type == ProviderType.GOOGLE:
                self._ocr_providers[provider_type] = GoogleVisionProvider(
                    self._google_api_key
                )

        return self._ocr_providers.get(provider_type)

    def get_translation_provider(
        self, provider_type: Optional[ProviderType] = None
    ) -> Optional[TranslationProvider]:
        if provider_type is None:
            if self._translation_provider_preference == "googlecloud":
                provider_type = ProviderType.GOOGLE
            elif self._translation_provider_preference == "llm":
                provider_type = ProviderType.LLM
            else:
                provider_type = ProviderType.FREE_GOOGLE

        if provider_type not in self._translation_providers:
            if provider_type == ProviderType.FREE_GOOGLE:
                self._translation_providers[provider_type] = FreeTranslateProvider()
            elif provider_type == ProviderType.GOOGLE:
                self._translation_providers[provider_type] = GoogleTranslateProvider(
                    self._google_api_key
                )
            elif provider_type == ProviderType.LLM:
                provider = LlmTranslateProvider(
                    base_url=self._llm_base_url,
                    api_key=self._llm_api_key,
                    model=self._llm_model,
                    system_prompt=self._llm_system_prompt,
                    disable_thinking=self._llm_disable_thinking,
                    parallel=self._llm_parallel,
                )
                if self._llm_game_prompt:
                    provider.configure(game_prompt=self._llm_game_prompt)
                self._translation_providers[provider_type] = provider

        return self._translation_providers.get(provider_type)

    def get_vision_provider(self) -> Optional[GeminiVisionProvider]:
        """Vision Providerを取得する。vision_mode=="off"ならNoneを返す。
        Vision専用設定が空の場合、LLM設定をフォールバックとして使用する。"""
        if self._vision_mode == "off":
            return None

        if self._vision_provider is None:
            self._vision_provider = GeminiVisionProvider(
                base_url=self._vision_base_url or self._llm_base_url,
                api_key=self._vision_api_key or self._llm_api_key,
                model=self._vision_model or self._llm_model,
                disable_thinking=self._llm_disable_thinking,
                custom_prompt=self._llm_system_prompt,
                game_prompt=self._llm_game_prompt,
            )
        return self._vision_provider

    async def recognize_text(
        self, image_data: bytes, language: str = "auto"
    ) -> List[TextRegion]:
        provider = self.get_ocr_provider()
        if provider and provider.is_available(language):
            provider_name = provider.name
            logger.debug(f"Using {provider_name} for OCR")
            return await provider.recognize(image_data, language)

        logger.warning("No OCR provider available")
        return []

    async def translate_text(
        self,
        texts: List[str],
        source_lang: str,
        target_lang: str,
        text_regions: List[dict] = None,
        image_bytes: bytes = None,
    ) -> List[str]:
        """翻訳を実行する。vision_mode=="assist"の場合、低信頼度領域を画像付きで処理。"""
        if not texts:
            return []

        provider = self.get_translation_provider()
        if not provider or not provider.is_available(source_lang, target_lang):
            logger.warning("No translation provider available")
            return texts

        provider_name = provider.name
        logger.debug(f"Using {provider_name} for translation")

        # Vision assistモードの場合、低信頼度領域を画像付きで処理
        if (
            self._vision_mode == "assist"
            and text_regions is not None
            and image_bytes is not None
        ):
            vision_provider = self.get_vision_provider()
            if vision_provider and vision_provider.is_available():
                return await self._translate_with_vision_assist(
                    provider, vision_provider, texts, text_regions, image_bytes,
                    source_lang, target_lang,
                )

        return await provider.translate_batch(texts, source_lang, target_lang)

    async def _translate_with_vision_assist(
        self,
        translation_provider: TranslationProvider,
        vision_provider: GeminiVisionProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """低信頼度領域を画像付きでVision Providerに翻訳依頼し、
        高信頼度領域はテキストのみで処理する。"""
        threshold = self._vision_assist_confidence_threshold

        high_conf_indices = []
        low_conf_indices = []
        for i, region in enumerate(text_regions):
            if i >= len(texts):
                break
            confidence = region.get("confidence", 1.0)
            logger.debug(
                f"  region[{i}] confidence={confidence:.3f} text='{texts[i][:30]}'"
            )
            if self._vision_assist_send_all or confidence < threshold:
                low_conf_indices.append(i)
            else:
                high_conf_indices.append(i)

        mode_label = "全件画像送信" if self._vision_assist_send_all else f"閾値{threshold}"
        logger.info(
            f"Vision assist({mode_label}): {len(low_conf_indices)}/{len(texts)} regions "
            f"(indices: {low_conf_indices})"
        )

        results = list(texts)  # デフォルトは原文

        async def _batch_task():
            if not high_conf_indices:
                return
            high_texts = [texts[i] for i in high_conf_indices]
            try:
                high_translated = await translation_provider.translate_batch(
                    high_texts, source_lang, target_lang
                )
                for j, idx in enumerate(high_conf_indices):
                    results[idx] = high_translated[j]
            except Exception as e:
                logger.error(f"高信頼度テキストのバッチ翻訳エラー: {e}")

        async def _image_task():
            if not low_conf_indices:
                return
            if self._vision_parallel:
                await self._vision_assist_parallel(
                    translation_provider, vision_provider,
                    texts, text_regions, image_bytes,
                    low_conf_indices, results, source_lang, target_lang,
                )
            else:
                await self._vision_assist_sequential(
                    translation_provider, vision_provider,
                    texts, text_regions, image_bytes,
                    low_conf_indices, results, source_lang, target_lang,
                )

        await asyncio.gather(_batch_task(), _image_task())

        return results

    async def _vision_assist_sequential(
        self,
        translation_provider: TranslationProvider,
        vision_provider: GeminiVisionProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        indices: List[int],
        results: List[str],
        source_lang: str,
        target_lang: str,
    ) -> None:
        """Vision assist: 画像付き翻訳を逐次実行する。"""
        for idx in indices:
            region = text_regions[idx]
            try:
                crop_b64 = self._crop_region_base64(image_bytes, region["rect"])
                if crop_b64:
                    results[idx] = await vision_provider.assist_translate(
                        ocr_text=texts[idx],
                        image_base64=crop_b64,
                        confidence=region.get("confidence", 0.0),
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                else:
                    logger.warning(f"  切り出し失敗、テキストのみで翻訳 (index {idx})")
                    results[idx] = await translation_provider.translate(
                        texts[idx], source_lang, target_lang
                    )
            except Exception as e:
                logger.warning(f"Vision assist翻訳エラー (index {idx}): {e}")
                try:
                    results[idx] = await translation_provider.translate(
                        texts[idx], source_lang, target_lang
                    )
                except Exception:
                    pass  # 原文のまま

    async def _vision_assist_parallel(
        self,
        translation_provider: TranslationProvider,
        vision_provider: GeminiVisionProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        indices: List[int],
        results: List[str],
        source_lang: str,
        target_lang: str,
    ) -> None:
        """Vision assist: 画像付き翻訳を並列実行する。"""
        # 先に全regionの画像を切り出し（サブプロセスなので逐次）
        crops = {}
        for idx in indices:
            crops[idx] = self._crop_region_base64(
                image_bytes, text_regions[idx]["rect"]
            )

        async def _translate_one(idx: int) -> tuple:
            crop_b64 = crops.get(idx)
            try:
                if crop_b64:
                    translated = await vision_provider.assist_translate(
                        ocr_text=texts[idx],
                        image_base64=crop_b64,
                        confidence=text_regions[idx].get("confidence", 0.0),
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                    return idx, translated
                else:
                    logger.warning(f"  切り出し失敗、テキストのみで翻訳 (index {idx})")
                    translated = await translation_provider.translate(
                        texts[idx], source_lang, target_lang
                    )
                    return idx, translated
            except Exception as e:
                logger.warning(f"Vision assist翻訳エラー (index {idx}): {e}")
                try:
                    translated = await translation_provider.translate(
                        texts[idx], source_lang, target_lang
                    )
                    return idx, translated
                except Exception:
                    return idx, None

        gathered = await asyncio.gather(
            *[_translate_one(idx) for idx in indices]
        )
        for idx, translated in gathered:
            if translated is not None:
                results[idx] = translated

    @staticmethod
    def _crop_region_base64(image_bytes: bytes, rect: dict) -> Optional[str]:
        """画像バイトデータからrect領域を切り出してBase64文字列を返す。

        Decky LoaderのPython 3.11ランタイムではPILを直接使えないため、
        システムPythonのサブプロセスで画像処理を行う。
        """
        left = rect.get("left", 0)
        top = rect.get("top", 0)
        right = rect.get("right", 0)
        bottom = rect.get("bottom", 0)

        if right <= left or bottom <= top:
            logger.warning(f"無効なrect: {rect}")
            return None

        try:
            python_path = ""
            for path in ['/usr/bin/python3', '/usr/bin/python3.13', '/usr/local/bin/python3']:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    python_path = path
                    break
            if not python_path:
                logger.error("システムPythonが見つかりません")
                return None

            script = """
import sys, io, base64
from PIL import Image

data = sys.stdin.buffer.read()
left, top, right, bottom = map(int, sys.argv[1:5])

img = Image.open(io.BytesIO(data))
# 画像サイズでクランプ
w, h = img.size
left = max(0, min(left, w))
top = max(0, min(top, h))
right = max(left + 1, min(right, w))
bottom = max(top + 1, min(bottom, h))

cropped = img.crop((left, top, right, bottom))
out = io.BytesIO()
cropped.save(out, format='PNG')
sys.stdout.write(base64.b64encode(out.getvalue()).decode())
"""
            env = os.environ.copy()
            plugin_dir = os.environ.get("DECKY_PLUGIN_DIR", "")
            if plugin_dir:
                bin_pm = os.path.join(plugin_dir, "bin", "py_modules")
                root_pm = os.path.join(plugin_dir, "py_modules")
                paths = [p for p in [bin_pm, root_pm] if os.path.exists(p)]
                if paths:
                    env['PYTHONPATH'] = os.pathsep.join(paths)
            env['PYTHONNOUSERSITE'] = '1'

            result = subprocess.run(
                [python_path, '-S', '-c', script,
                 str(left), str(top), str(right), str(bottom)],
                input=image_bytes,
                capture_output=True,
                timeout=10,
                env=env,
            )

            if result.returncode != 0:
                logger.error(f"画像切り出しサブプロセスエラー: {result.stderr.decode()[:500]}")
                return None

            b64 = result.stdout.decode().strip()
            if not b64:
                logger.error("画像切り出し結果が空です")
                return None

            logger.debug(
                f"画像切り出し完了: rect=({left},{top},{right},{bottom}), "
                f"base64 length={len(b64)}"
            )
            return b64

        except subprocess.TimeoutExpired:
            logger.error("画像切り出しがタイムアウトしました")
            return None
        except Exception as e:
            logger.error(f"画像切り出しエラー: {e}")
            return None

    def _to_original_pixel_coordinates(
        self, rect: dict,
        original_w: int, original_h: int,
        compressed_w: int, compressed_h: int,
    ) -> dict:
        """LLM返却座標 → 元画像のピクセル座標に変換する。"""
        l, t = float(rect["left"]), float(rect["top"])
        r, b = float(rect["right"]), float(rect["bottom"])

        # Stage 1: normalized → compressed pixel
        if self._vision_coordinate_mode == "normalized":
            l = l * compressed_w / 1000
            t = t * compressed_h / 1000
            r = r * compressed_w / 1000
            b = b * compressed_h / 1000

        # Stage 2: compressed pixel → original pixel
        if compressed_w != original_w or compressed_h != original_h:
            scale_x = original_w / compressed_w
            scale_y = original_h / compressed_h
            l, r = l * scale_x, r * scale_x
            t, b = t * scale_y, b * scale_y

        return {
            "left":   max(0, min(int(l), original_w)),
            "top":    max(0, min(int(t), original_h)),
            "right":  max(0, min(int(r), original_w)),
            "bottom": max(0, min(int(b), original_h)),
        }

    @staticmethod
    def _resize_and_compress_image(
        image_bytes: bytes, max_long_side: int = 768, quality: int = 80,
    ) -> Optional[tuple]:
        """画像をリサイズ・JPEG圧縮して (base64_str, width, height) を返す。"""
        try:
            python_path = ""
            for path in ['/usr/bin/python3', '/usr/bin/python3.13', '/usr/local/bin/python3']:
                if os.path.exists(path) and os.access(path, os.X_OK):
                    python_path = path
                    break
            if not python_path:
                logger.error("システムPythonが見つかりません")
                return None

            script = f"""
import sys, io, base64, json
from PIL import Image

data = sys.stdin.buffer.read()
img = Image.open(io.BytesIO(data))
w, h = img.size
max_side = {max_long_side}
if max(w, h) > max_side:
    ratio = max_side / max(w, h)
    w, h = int(w * ratio), int(h * ratio)
    img = img.resize((w, h), Image.LANCZOS)
img = img.convert('RGB')
out = io.BytesIO()
img.save(out, format='JPEG', quality={quality})
b64 = base64.b64encode(out.getvalue()).decode()
json.dump({{"b64": b64, "w": w, "h": h}}, sys.stdout)
"""
            env = os.environ.copy()
            plugin_dir = os.environ.get("DECKY_PLUGIN_DIR", "")
            if plugin_dir:
                bin_pm = os.path.join(plugin_dir, "bin", "py_modules")
                root_pm = os.path.join(plugin_dir, "py_modules")
                paths = [p for p in [bin_pm, root_pm] if os.path.exists(p)]
                if paths:
                    env['PYTHONPATH'] = os.pathsep.join(paths)
            env['PYTHONNOUSERSITE'] = '1'

            import json as json_mod
            result = subprocess.run(
                [python_path, '-S', '-c', script],
                input=image_bytes,
                capture_output=True,
                timeout=10,
                env=env,
            )
            if result.returncode != 0:
                logger.error(f"画像圧縮サブプロセスエラー: {result.stderr.decode()[:500]}")
                return None

            data = json_mod.loads(result.stdout.decode())
            logger.debug(
                f"画像圧縮完了: {data['w']}x{data['h']}, "
                f"base64 length={len(data['b64'])}"
            )
            return (data["b64"], data["w"], data["h"])

        except subprocess.TimeoutExpired:
            logger.error("画像圧縮がタイムアウトしました")
            return None
        except Exception as e:
            logger.error(f"画像圧縮エラー: {e}")
            return None

    async def preflight_vision_check(self) -> dict:
        """Vision + JSON構造化出力対応を検証する（非同期）。"""
        vision_provider = self.get_vision_provider()
        if not vision_provider:
            return {"ok": False, "message": "Vision Providerが設定されていません"}
        if not vision_provider.is_available():
            return {"ok": False, "message": "Vision用のbase_urlとmodelを設定してください"}

        success, message = await vision_provider.preflight_check()
        return {"ok": success, "message": message}

    async def recognize_and_translate(
        self,
        image_bytes: bytes,
        source_lang: str,
        target_lang: str,
        image_width: int,
        image_height: int,
    ) -> Optional[List[dict]]:
        """Vision direct: スクリーンショットから直接テキスト検出+翻訳。"""
        vision_provider = self.get_vision_provider()
        if not vision_provider or not vision_provider.is_available():
            logger.warning("Vision direct: Vision Providerが利用不可")
            return None

        image_b64 = base64.b64encode(image_bytes).decode()

        try:
            raw_regions, reported_mode = await vision_provider.direct_translate(
                image_b64, source_lang, target_lang,
                image_width, image_height,
            )
        except Exception as e:
            logger.error(f"Vision direct失敗: {e}")
            return None

        # coordinate_modeの判定: LLMの自己申告を優先
        if reported_mode and "pixel" in str(reported_mode).lower():
            effective_mode = "pixel"
            logger.info(f"coordinate_mode: LLM自己申告 pixel ({reported_mode})")
        else:
            effective_mode = "normalized"
            if reported_mode:
                logger.info(f"coordinate_mode: LLM自己申告 normalized ({reported_mode})")
        self._vision_coordinate_mode = effective_mode

        # 座標変換 + TranslatedRegion互換形式
        result = []
        for r in raw_regions:
            pixel_rect = self._to_original_pixel_coordinates(
                r["rect"],
                image_width, image_height,
                image_width, image_height,
            )
            result.append({
                "text": r["text"],
                "translatedText": r["translated_text"],
                "rect": pixel_rect,
                "confidence": 1.0,
                "isDialog": False,
            })

        logger.info(f"Vision direct完了: {len(result)} regions")
        return result

    def get_provider_status(self) -> dict:
        ocr_provider = self.get_ocr_provider()
        trans_provider = self.get_translation_provider()

        status = {
            "use_free_providers": self._use_free_providers,
            "ocr_provider_preference": self._ocr_provider_preference,
            "translation_provider_preference": self._translation_provider_preference,
            "google_api_configured": bool(self._google_api_key),
            "ocr_provider": ocr_provider.name if ocr_provider else "None",
            "translation_provider": trans_provider.name if trans_provider else "None",
            "ocr_available": ocr_provider.is_available() if ocr_provider else False,
            "translation_available": trans_provider.is_available("auto", "en") if trans_provider else False,
        }

        if self._ocr_provider_preference == "ocrspace" and ocr_provider:
            if hasattr(ocr_provider, 'get_usage_stats'):
                status["ocr_usage"] = ocr_provider.get_usage_stats()

        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr is None:
            rapidocr = RapidOCRProvider(min_confidence=self._rapidocr_confidence)
        status["rapidocr_available"] = rapidocr.is_available()
        status["rapidocr_languages"] = rapidocr.get_supported_languages() if rapidocr.is_available() else []
        status["rapidocr_info"] = rapidocr.get_rapidocr_info()
        status["rapidocr_error"] = rapidocr.get_init_error()

        return status

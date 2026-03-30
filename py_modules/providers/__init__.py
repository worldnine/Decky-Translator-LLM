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
)
from .google_ocr import GoogleVisionProvider
from .google_translate import GoogleTranslateProvider
from .ocrspace import OCRSpaceProvider
from .free_translate import FreeTranslateProvider
from .rapidocr_provider import RapidOCRProvider
from .llm_translate import LlmTranslateProvider

logger = logging.getLogger(__name__)

# Export all public classes
__all__ = [
    'OCRProvider',
    'TranslationProvider',
    'ProviderType',
    'TextRegion',
    'NetworkError',
    'ApiKeyError',
    'RateLimitError',
    'GoogleVisionProvider',
    'GoogleTranslateProvider',
    'OCRSpaceProvider',
    'FreeTranslateProvider',
    'RapidOCRProvider',
    'LlmTranslateProvider',
    'ProviderManager',
]


class ProviderManager:
    """Factory and manager for OCR and Translation providers."""

    def __init__(self):
        """Initialize the provider manager."""
        # Provider instances (created on demand)
        self._ocr_providers = {}
        self._translation_providers = {}

        # Configuration
        self._use_free_providers = True  # Default to free providers
        self._google_api_key = ""
        self._ocr_provider_preference = "rapidocr"  # "rapidocr", "ocrspace", or "googlecloud"
        self._translation_provider_preference = "freegoogle"  # "freegoogle", "googlecloud", or "llm"
        self._rapidocr_confidence = 0.5  # Default RapidOCR confidence threshold (0.0-1.0)
        self._rapidocr_box_thresh = 0.5  # Default RapidOCR box detection threshold (0.0-1.0)
        self._rapidocr_unclip_ratio = 1.6  # Default RapidOCR box expansion ratio (1.0-3.0)

        # LLM翻訳プロバイダー設定
        self._llm_base_url = ""
        self._llm_api_key = ""
        self._llm_model = ""
        self._llm_system_prompt = ""
        self._llm_disable_thinking = True

        # LLM画像再認識設定
        self._llm_image_rerecognition = False
        self._llm_image_confidence_threshold = 0.95
        self._llm_image_send_all = False
        self._llm_parallel = True

        logger.debug("ProviderManager initialized")

    def configure_llm(
        self,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        system_prompt: str = None,
        disable_thinking: bool = None,
        image_rerecognition: bool = None,
        image_confidence_threshold: float = None,
        image_send_all: bool = None,
        parallel: bool = None,
    ) -> None:
        """LLM翻訳プロバイダーの設定を更新する。"""
        if base_url is not None:
            self._llm_base_url = base_url
        if api_key is not None:
            self._llm_api_key = api_key
        if model is not None:
            self._llm_model = model
        if system_prompt is not None:
            self._llm_system_prompt = system_prompt
        if disable_thinking is not None:
            self._llm_disable_thinking = disable_thinking
        if image_rerecognition is not None:
            self._llm_image_rerecognition = image_rerecognition
        if image_confidence_threshold is not None:
            self._llm_image_confidence_threshold = image_confidence_threshold
        if image_send_all is not None:
            self._llm_image_send_all = image_send_all
        if parallel is not None:
            self._llm_parallel = parallel

        # 既存のLLMプロバイダーインスタンスがあれば更新
        llm_provider = self._translation_providers.get(ProviderType.LLM)
        if llm_provider:
            llm_provider.configure(
                base_url=base_url, api_key=api_key,
                model=model, system_prompt=system_prompt,
                disable_thinking=disable_thinking,
                parallel=parallel,
            )
        logger.debug(
            f"LLM config updated: base_url={self._llm_base_url}, "
            f"model={self._llm_model}, disable_thinking={self._llm_disable_thinking}, "
            f"image_rerecognition={self._llm_image_rerecognition}, "
            f"image_confidence_threshold={self._llm_image_confidence_threshold}"
        )

    def configure(
        self,
        use_free_providers: bool = True,
        google_api_key: str = "",
        ocr_provider: str = "",
        translation_provider: str = ""
    ) -> None:
        """
        Configure provider preferences.

        Args:
            use_free_providers: If True, use OCR.space + free Google Translate.
                                If False, use Google Cloud APIs (requires API key).
                                (Deprecated: use ocr_provider and translation_provider instead)
            google_api_key: Google Cloud API key (only needed for googlecloud providers)
            ocr_provider: OCR provider preference - "rapidocr", "ocrspace", or "googlecloud"
            translation_provider: Translation provider preference - "freegoogle" or "googlecloud"
        """
        self._google_api_key = google_api_key

        # Handle ocr_provider setting (new way)
        if ocr_provider:
            self._ocr_provider_preference = ocr_provider
            # Derive use_free_providers for backwards compatibility
            self._use_free_providers = (ocr_provider != "googlecloud")
        else:
            # Backwards compatibility: derive from use_free_providers
            self._use_free_providers = use_free_providers
            self._ocr_provider_preference = "rapidocr" if use_free_providers else "googlecloud"

        # Handle translation_provider setting
        if translation_provider:
            self._translation_provider_preference = translation_provider
        elif not translation_provider and ocr_provider:
            # Backwards compatibility: if only ocr_provider is set, derive translation from it
            # googlecloud OCR -> googlecloud translation, others -> freegoogle
            self._translation_provider_preference = "googlecloud" if ocr_provider == "googlecloud" else "freegoogle"
        elif not use_free_providers:
            # Legacy: use_free_providers=False means Google Cloud for both
            self._translation_provider_preference = "googlecloud"

        # Update Google Cloud providers with new API key
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
        """
        Set the RapidOCR confidence threshold.

        Args:
            confidence: Minimum confidence (0.0-1.0) for RapidOCR results.
        """
        self._rapidocr_confidence = confidence
        # Update existing RapidOCR provider if it exists
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_min_confidence(confidence)
        logger.debug(f"RapidOCR confidence set to {confidence}")

    def set_rapidocr_box_thresh(self, box_thresh: float) -> None:
        """
        Set the RapidOCR box detection threshold.

        Args:
            box_thresh: Detection box confidence (0.0-1.0). Lower values detect more text.
        """
        self._rapidocr_box_thresh = box_thresh
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_box_thresh(box_thresh)
        logger.debug(f"RapidOCR box_thresh set to {box_thresh}")

    def set_rapidocr_unclip_ratio(self, unclip_ratio: float) -> None:
        """
        Set the RapidOCR box expansion ratio.

        Args:
            unclip_ratio: Box expansion ratio (1.0-3.0). Higher values expand detected boxes.
        """
        self._rapidocr_unclip_ratio = unclip_ratio
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr:
            rapidocr.set_unclip_ratio(unclip_ratio)
        logger.debug(f"RapidOCR unclip_ratio set to {unclip_ratio}")

    def get_ocr_provider(
        self,
        provider_type: Optional[ProviderType] = None
    ) -> Optional[OCRProvider]:
        """
        Get OCR provider, creating if necessary.

        Args:
            provider_type: Specific provider type, or None for default based on preference

        Returns:
            OCRProvider instance or None
        """
        if provider_type is None:
            # Determine provider type based on preference
            if self._ocr_provider_preference == "rapidocr":
                provider_type = ProviderType.RAPIDOCR
            elif self._ocr_provider_preference == "ocrspace":
                provider_type = ProviderType.OCR_SPACE
            else:  # "googlecloud"
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
        self,
        provider_type: Optional[ProviderType] = None
    ) -> Optional[TranslationProvider]:
        """
        Get translation provider, creating if necessary.

        Args:
            provider_type: Specific provider type, or None for default based on preference

        Returns:
            TranslationProvider instance or None
        """
        if provider_type is None:
            # Use translation provider preference (independent of OCR choice)
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
                self._translation_providers[provider_type] = LlmTranslateProvider(
                    base_url=self._llm_base_url,
                    api_key=self._llm_api_key,
                    model=self._llm_model,
                    system_prompt=self._llm_system_prompt,
                    disable_thinking=self._llm_disable_thinking,
                    parallel=self._llm_parallel,
                )

        return self._translation_providers.get(provider_type)

    async def recognize_text(
        self,
        image_data: bytes,
        language: str = "auto"
    ) -> List[TextRegion]:
        """
        Perform OCR with automatic provider selection.

        Args:
            image_data: Raw image bytes
            language: Language code or "auto"

        Returns:
            List of TextRegion objects
        """
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
        """
        Perform translation with automatic provider selection.

        画像再認識が有効な場合、低信頼度のテキスト領域は切り出し画像付きで
        LLMに送り、OCR再認識+翻訳を一括で行う。

        Args:
            texts: List of texts to translate
            source_lang: Source language code
            target_lang: Target language code
            text_regions: OCR結果のTextRegion辞書リスト（画像再認識用、任意）
            image_bytes: スクリーンショットのバイトデータ（画像再認識用、任意）

        Returns:
            List of translated texts
        """
        if not texts:
            return []

        provider = self.get_translation_provider()
        if not provider or not provider.is_available(source_lang, target_lang):
            logger.warning("No translation provider available")
            return texts

        provider_name = provider.name
        logger.debug(f"Using {provider_name} for translation")

        # 画像再認識が有効かつLLMプロバイダーの場合、低信頼度領域を画像付きで処理
        if (
            self._llm_image_rerecognition
            and self._translation_provider_preference == "llm"
            and text_regions is not None
            and image_bytes is not None
            and isinstance(provider, LlmTranslateProvider)
        ):
            return await self._translate_with_image_rerecognition(
                provider, texts, text_regions, image_bytes,
                source_lang, target_lang,
            )

        return await provider.translate_batch(texts, source_lang, target_lang)

    async def _translate_with_image_rerecognition(
        self,
        provider: LlmTranslateProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        source_lang: str,
        target_lang: str,
    ) -> List[str]:
        """低信頼度領域を画像付きでLLMに翻訳依頼し、高信頼度領域はテキストのみで処理する。"""
        threshold = self._llm_image_confidence_threshold

        # 全件送信モードまたは閾値ベースで分類
        high_conf_indices = []
        low_conf_indices = []
        for i, region in enumerate(text_regions):
            if i >= len(texts):
                break
            confidence = region.get("confidence", 1.0)
            logger.debug(
                f"  region[{i}] confidence={confidence:.3f} text='{texts[i][:30]}'"
            )
            if self._llm_image_send_all or confidence < threshold:
                low_conf_indices.append(i)
            else:
                high_conf_indices.append(i)

        mode_label = "全件画像送信" if self._llm_image_send_all else f"閾値{threshold}"
        logger.info(
            f"画像再認識({mode_label}): {len(low_conf_indices)}/{len(texts)} regions "
            f"(indices: {low_conf_indices})"
        )

        # 結果配列を初期化
        results = list(texts)  # デフォルトは原文

        # バッチ翻訳と画像翻訳を並列実行
        async def _batch_task():
            if not high_conf_indices:
                return
            high_texts = [texts[i] for i in high_conf_indices]
            try:
                high_translated = await provider.translate_batch(
                    high_texts, source_lang, target_lang
                )
                for j, idx in enumerate(high_conf_indices):
                    results[idx] = high_translated[j]
            except Exception as e:
                logger.error(f"高信頼度テキストのバッチ翻訳エラー: {e}")

        async def _image_task():
            if not low_conf_indices:
                return
            if self._llm_parallel:
                await self._translate_images_parallel(
                    provider, texts, text_regions, image_bytes,
                    low_conf_indices, results, source_lang, target_lang,
                )
            else:
                await self._translate_images_sequential(
                    provider, texts, text_regions, image_bytes,
                    low_conf_indices, results, source_lang, target_lang,
                )

        await asyncio.gather(_batch_task(), _image_task())

        return results

    async def _translate_images_sequential(
        self,
        provider: LlmTranslateProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        indices: List[int],
        results: List[str],
        source_lang: str,
        target_lang: str,
    ) -> None:
        """画像付き翻訳を逐次実行する。"""
        for idx in indices:
            region = text_regions[idx]
            try:
                crop_b64 = self._crop_region_base64(image_bytes, region["rect"])
                if crop_b64:
                    results[idx] = await provider.translate_with_image(
                        ocr_text=texts[idx],
                        image_base64=crop_b64,
                        confidence=region.get("confidence", 0.0),
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                else:
                    logger.warning(f"  切り出し失敗、テキストのみで翻訳 (index {idx})")
                    results[idx] = await provider.translate(
                        texts[idx], source_lang, target_lang
                    )
            except Exception as e:
                logger.warning(f"画像再認識翻訳エラー (index {idx}): {e}")
                try:
                    results[idx] = await provider.translate(
                        texts[idx], source_lang, target_lang
                    )
                except Exception:
                    pass  # 原文のまま

    async def _translate_images_parallel(
        self,
        provider: LlmTranslateProvider,
        texts: List[str],
        text_regions: List[dict],
        image_bytes: bytes,
        indices: List[int],
        results: List[str],
        source_lang: str,
        target_lang: str,
    ) -> None:
        """画像付き翻訳を並列実行する（asyncio.gather）。"""
        # 先に全regionの画像を切り出し（サブプロセスなので逐次）
        crops = {}
        for idx in indices:
            crops[idx] = self._crop_region_base64(
                image_bytes, text_regions[idx]["rect"]
            )

        # 並列API呼び出し用のコルーチンを構築
        async def _translate_one(idx: int) -> tuple:
            crop_b64 = crops.get(idx)
            try:
                if crop_b64:
                    translated = await provider.translate_with_image(
                        ocr_text=texts[idx],
                        image_base64=crop_b64,
                        confidence=text_regions[idx].get("confidence", 0.0),
                        source_lang=source_lang,
                        target_lang=target_lang,
                    )
                    return idx, translated
                else:
                    logger.warning(f"  切り出し失敗、テキストのみで翻訳 (index {idx})")
                    translated = await provider.translate(
                        texts[idx], source_lang, target_lang
                    )
                    return idx, translated
            except Exception as e:
                logger.warning(f"画像再認識翻訳エラー (index {idx}): {e}")
                try:
                    translated = await provider.translate(
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

    def get_provider_status(self) -> dict:
        """
        Get current provider configuration and availability status.

        Returns:
            Dictionary with provider status information
        """
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

        # Add OCR.space usage stats if using ocrspace (OCR.space) provider
        if self._ocr_provider_preference == "ocrspace" and ocr_provider:
            if hasattr(ocr_provider, 'get_usage_stats'):
                status["ocr_usage"] = ocr_provider.get_usage_stats()

        # Add RapidOCR availability info
        rapidocr = self._ocr_providers.get(ProviderType.RAPIDOCR)
        if rapidocr is None:
            # Create temporarily to check availability
            rapidocr = RapidOCRProvider(min_confidence=self._rapidocr_confidence)
        status["rapidocr_available"] = rapidocr.is_available()
        status["rapidocr_languages"] = rapidocr.get_supported_languages() if rapidocr.is_available() else []
        status["rapidocr_info"] = rapidocr.get_rapidocr_info()
        status["rapidocr_error"] = rapidocr.get_init_error()

        return status

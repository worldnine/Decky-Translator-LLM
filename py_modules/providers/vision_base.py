# providers/vision_base.py
# Vision翻訳プロバイダーの抽象基底クラス

from abc import ABC, abstractmethod
from typing import List, Optional


class VisionProvider(ABC):
    """Vision翻訳プロバイダーの抽象基底クラス。

    Vision機能は以下2モードを提供する:
    - assist: OCR低信頼度領域の画像付き再認識+翻訳
    - direct: OCRバイパスでスクリーンショットから直接テキスト検出+翻訳
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """プロバイダー名を返す。"""
        pass

    @abstractmethod
    async def assist_translate(
        self,
        ocr_text: str,
        image_base64: str,
        confidence: float,
        source_lang: str,
        target_lang: str,
    ) -> str:
        """OCR低信頼度領域の画像付き再認識+翻訳。

        Args:
            ocr_text: OCRが認識したテキスト（参考情報）
            image_base64: 切り出し画像のBase64文字列
            confidence: OCRの信頼度スコア（0.0-1.0）
            source_lang: ソース言語コード
            target_lang: ターゲット言語コード

        Returns:
            翻訳済みテキスト
        """
        pass

    @abstractmethod
    async def direct_translate(
        self,
        image_base64: str,
        source_lang: str,
        target_lang: str,
        image_width: int,
        image_height: int,
    ) -> tuple:
        """スクリーンショットから直接テキスト検出+翻訳（OCRバイパス）。

        Args:
            image_base64: フルスクリーンショットのBase64文字列
            source_lang: ソース言語コード
            target_lang: ターゲット言語コード
            image_width: 画像の幅（ピクセル）
            image_height: 画像の高さ（ピクセル）

        Returns:
            (regions_list, reported_coordinate_mode)
            regions_list: [{"text": str, "translated_text": str, "rect": {...}}]
        """
        pass

    @abstractmethod
    async def preflight_check(self) -> tuple:
        """Vision + JSON構造化出力の対応を事前検証する。

        Returns:
            (success: bool, error_message: str)
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """プロバイダーが利用可能か（設定済みか）。"""
        pass

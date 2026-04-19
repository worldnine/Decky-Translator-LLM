# providers/__init__.py
# Provider factory and manager — Gemini Vision専用構成

import base64
import logging
from typing import List, Optional

from .base import (
    NetworkError,
    ApiKeyError,
    RateLimitError,
    ConfigurationError,
)
from .circuit_breaker import CircuitBreaker
from .vision_base import VisionProvider
from .gemini_vision import GeminiVisionProvider

logger = logging.getLogger(__name__)

# Export all public classes
__all__ = [
    'VisionProvider',
    'NetworkError',
    'ApiKeyError',
    'RateLimitError',
    'ConfigurationError',
    'GeminiVisionProvider',
    'ProviderManager',
]


# Primary モデル（preview系）の応答遅延を早めに見切って Fallback に切替
# 実機ログで「Primary が 53秒かけて 200 を返す」ケースがあり体感悪化していた
_PRIMARY_TIMEOUT_SEC = 15.0
# Fallback は応答の信頼性を優先して長めに取る
_FALLBACK_TIMEOUT_SEC = 60.0


class ProviderManager:
    """Gemini Vision専用のプロバイダーマネージャー。
    翻訳の正式経路は vision_translate（recognize_and_translate）のみ。"""

    def __init__(self):
        self._vision_provider: Optional[GeminiVisionProvider] = None

        # Gemini設定
        self._gemini_base_url = ""
        self._gemini_api_key = ""
        self._gemini_model = ""
        # Primary が 503 等で失敗した場合の切替先（空文字列ならフォールバック無し）
        self._gemini_fallback_model = ""
        self._gemini_disable_thinking = True
        self._gemini_parallel = True
        self._gemini_system_prompt = ""
        self._gemini_game_prompt = ""

        # Visionモード設定
        self._vision_mode = "direct"
        self._vision_coordinate_mode = "pixel"

        # 翻訳中のリトライ/フォールバック状態（フロントのポーリング用）
        # recognize_and_translate 実行中のみセットされ、終了時にクリアされる
        # 形式: {event: "translating"|"retry"|"fallback", model, attempt?, max?, delay?, status?}
        self._retry_status: Optional[dict] = None
        # 現在試行中のモデル名（コールバックから参照する）
        self._current_model: str = ""

        # Primary モデル用のサーキットブレーカー
        # 5分以内に3回 server_busy で OPEN、5分後 HALF_OPEN
        self._circuit = CircuitBreaker(
            threshold=3, window_sec=300.0, open_sec=300.0,
        )

        logger.debug("ProviderManager initialized")

    def _record_retry(self, info: dict) -> None:
        """LlmApiClient からリトライ発生時に呼ばれるコールバック。
        info: {attempt, max, delay, status} を含む。現在モデル名を上乗せして保存。"""
        self._retry_status = {
            **info,
            "event": "retry",
            "model": self._current_model,
        }

    def _record_translating(self, model: str) -> None:
        self._current_model = model
        self._retry_status = {"event": "translating", "model": model}

    def _record_fallback(self, next_model: str) -> None:
        self._retry_status = {"event": "fallback", "model": next_model}

    def get_retry_status(self) -> Optional[dict]:
        """現在のリトライ状態を返す。翻訳中でなければ None。"""
        return self._retry_status

    def configure_vision(
        self,
        mode: str = None,
        base_url: str = None,
        api_key: str = None,
        model: str = None,
        fallback_model: str = None,
        disable_thinking: bool = None,
        parallel: bool = None,
        system_prompt: str = None,
        game_prompt: str = None,
        coordinate_mode: str = None,
    ) -> None:
        """Gemini Vision設定を更新する。"""
        if mode is not None:
            self._vision_mode = mode
        if base_url is not None:
            self._gemini_base_url = base_url
        if api_key is not None:
            self._gemini_api_key = api_key
        if model is not None:
            self._gemini_model = model
        if fallback_model is not None:
            self._gemini_fallback_model = fallback_model
        if disable_thinking is not None:
            self._gemini_disable_thinking = disable_thinking
        if parallel is not None:
            self._gemini_parallel = parallel
        if system_prompt is not None:
            self._gemini_system_prompt = system_prompt
        if game_prompt is not None:
            self._gemini_game_prompt = game_prompt
        if coordinate_mode is not None:
            self._vision_coordinate_mode = coordinate_mode

        # 既存のVision Providerがあれば設定を反映
        if self._vision_provider:
            self._vision_provider.configure(
                base_url=self._gemini_base_url,
                api_key=self._gemini_api_key,
                model=self._gemini_model,
                disable_thinking=self._gemini_disable_thinking,
                custom_prompt=self._gemini_system_prompt,
                game_prompt=self._gemini_game_prompt,
            )

        logger.debug(
            f"Vision config updated: mode={self._vision_mode}, "
            f"model={self._gemini_model}, "
            f"parallel={self._gemini_parallel}"
        )

    def get_vision_provider(self) -> Optional[GeminiVisionProvider]:
        """Vision Providerを取得する。vision_mode=="off"ならNoneを返す。"""
        if self._vision_mode == "off":
            return None

        if self._vision_provider is None:
            self._vision_provider = GeminiVisionProvider(
                base_url=self._gemini_base_url,
                api_key=self._gemini_api_key,
                model=self._gemini_model,
                disable_thinking=self._gemini_disable_thinking,
                custom_prompt=self._gemini_system_prompt,
                game_prompt=self._gemini_game_prompt,
            )
        return self._vision_provider

    def _create_vision_provider_for_preflight(self) -> Optional[GeminiVisionProvider]:
        """preflight用にVision Providerを一時生成する（キャッシュしない）。
        現在の_vision_modeに関係なく、設定があれば生成する。"""
        return GeminiVisionProvider(
            base_url=self._gemini_base_url,
            api_key=self._gemini_api_key,
            model=self._gemini_model,
            disable_thinking=self._gemini_disable_thinking,
        )

    async def preflight_vision_check(self, mode: str = None) -> dict:
        """Vision + JSON構造化出力対応を検証する（非同期）。
        mode引数を指定すると、現在の_vision_modeに関係なくpreflight検証を実行する。"""
        if mode:
            vision_provider = self._create_vision_provider_for_preflight()
        else:
            vision_provider = self.get_vision_provider()
        if not vision_provider:
            return {"ok": False, "message": "Vision Providerが設定されていません"}
        if not vision_provider.is_available():
            return {"ok": False, "message": "Vision用のbase_urlとmodelを設定してください"}

        success, message = await vision_provider.preflight_check()
        return {"ok": success, "message": message}

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

    def _is_server_busy_error(self, exc: Exception) -> bool:
        """Primary の「実質的な混雑シグナル」を識別する。
        サーキットブレーカーのカウント対象を限定するため。

        対象:
        - 5xx 系 NetworkError: "Gemini API returned status 503" 等
        - Timeout 由来 NetworkError: "Geminiサーバーがタイムアウトしました"
          （Primary が遅延して応答を返さない状態もサーバー側過負荷の兆候）
        """
        if not isinstance(exc, NetworkError):
            return False
        msg = str(exc)
        if any(f"status {code}" in msg for code in ("500", "502", "503", "504")):
            return True
        # Timeout メッセージのマッチ（日本語・英語両対応）
        if "タイムアウト" in msg or "timeout" in msg.lower():
            return True
        return False

    async def _translate_with_fallback(
        self,
        vision_provider: GeminiVisionProvider,
        image_b64: str,
        source_lang: str,
        target_lang: str,
        image_width: int,
        image_height: int,
    ) -> tuple:
        """Primary → Fallback の順に翻訳を試行する。

        各モデルはリトライなし（disable_retry=True）。
        Primary は短い timeout で「遅延応答」を早めに見切って Fallback へ切替。

        サーキット状態:
          - CLOSED / HALF_OPEN: Primary（短 timeout）→ 失敗なら Fallback
          - OPEN: Primary スキップ、Fallback から開始
        """
        circuit_state = self._circuit.allow()

        # 試行順を決定: (model, is_primary, timeout)
        attempts: list[tuple[str, bool, float]] = []
        if circuit_state != CircuitBreaker.STATE_OPEN:
            attempts.append((
                self._gemini_model,
                True,
                _PRIMARY_TIMEOUT_SEC,
            ))
        else:
            logger.info(
                f"Circuit OPEN、Primary({self._gemini_model})スキップ、Fallbackから開始"
            )
        if self._gemini_fallback_model and self._gemini_fallback_model != self._gemini_model:
            attempts.append((
                self._gemini_fallback_model,
                False,
                _FALLBACK_TIMEOUT_SEC,
            ))

        if not attempts:
            # Primary が OPEN でかつ Fallback 未設定 → これは設定ミス
            raise NetworkError(
                "Primary モデルがサーキット OPEN かつ Fallback モデル未設定"
            )

        last_exc: Optional[Exception] = None
        for i, (model, is_primary, timeout) in enumerate(attempts):
            # VisionProvider のモデルを差し替え
            vision_provider.configure(model=model)
            self._record_translating(model)
            try:
                result = await vision_provider.direct_translate(
                    image_b64, source_lang, target_lang,
                    image_width, image_height,
                    on_retry=self._record_retry,
                    disable_retry=True,
                    timeout=timeout,
                )
                if is_primary:
                    self._circuit.record_success()
                return result
            except (NetworkError, RateLimitError) as e:
                last_exc = e
                if is_primary and self._is_server_busy_error(e):
                    self._circuit.record_failure()
                # まだ次の試行があれば fallback に切り替え
                is_last = (i == len(attempts) - 1)
                if not is_last:
                    next_model = attempts[i + 1][0]
                    logger.warning(
                        f"{model} で失敗({type(e).__name__}): {e}。"
                        f"{next_model} にフォールバック"
                    )
                    self._record_fallback(next_model)
                    continue
                # 最後のモデルも失敗
                raise
            except (ApiKeyError, ConfigurationError):
                # 認証・設定エラーはフォールバックしても解決しない
                raise

        # ここに到達するのは全試行失敗時のみ（raise で抜けていない稀なパス）
        raise last_exc or NetworkError("翻訳に失敗しました")

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

        # リトライ状態を初期化（前回の残骸をクリア）
        self._retry_status = None
        try:
            raw_regions, reported_mode = await self._translate_with_fallback(
                vision_provider, image_b64, source_lang, target_lang,
                image_width, image_height,
            )
        except (NetworkError, ApiKeyError, RateLimitError, ConfigurationError) as e:
            # フロントのエラーハンドリング（vision_translate RPC）に委ねる
            logger.error(f"Vision direct失敗: {type(e).__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"Vision direct 予期せぬエラー: {e}")
            return None
        finally:
            # 翻訳終了時にリトライ状態をクリア（ポーリング側が None を受け取れるように）
            self._retry_status = None
            # Primary モデルに念のため戻しておく（次回呼び出し時のため）
            if self._gemini_model:
                vision_provider.configure(model=self._gemini_model)

        # coordinate_modeの判定: LLMの自己申告を優先、未申告時は既存設定を維持
        if reported_mode and "pixel" in str(reported_mode).lower():
            effective_mode = "pixel"
            logger.info(f"coordinate_mode: LLM自己申告 pixel ({reported_mode})")
        elif reported_mode:
            effective_mode = "normalized"
            logger.info(f"coordinate_mode: LLM自己申告 normalized ({reported_mode})")
        else:
            effective_mode = self._vision_coordinate_mode
            logger.info(f"coordinate_mode: 未申告、既存設定を維持 ({effective_mode})")
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

    async def describe_screen(
        self,
        image_bytes: bytes,
        image_width: int,
        image_height: int,
        prompt: str = None,
    ) -> Optional[dict]:
        """攻略支援向け画面説明。構造化JSONを返す。"""
        vision_provider = self.get_vision_provider()
        if not vision_provider or not vision_provider.is_available():
            logger.warning("describe_screen: Vision Providerが利用不可")
            return None

        image_b64 = base64.b64encode(image_bytes).decode()

        try:
            result = await vision_provider.describe_screen(
                image_b64, image_width, image_height, prompt=prompt,
            )
        except (NetworkError, ApiKeyError, RateLimitError, ConfigurationError) as e:
            logger.error(f"describe_screen失敗: {type(e).__name__}: {e}")
            raise
        except Exception as e:
            logger.error(f"describe_screen 予期せぬエラー: {e}")
            return None

        logger.info(f"describe_screen完了: summary={result.get('summary', '')[:50]}")
        return result

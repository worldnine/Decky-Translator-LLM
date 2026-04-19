# tests/test_provider_manager_vision.py
# ProviderManager のGemini Vision専用構成テスト

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from py_modules.providers import ProviderManager
from py_modules.providers.base import NetworkError
from py_modules.providers.circuit_breaker import CircuitBreaker


class TestConfigureVision:
    """configure_vision() のテスト。"""

    def test_デフォルト設定(self):
        pm = ProviderManager()
        assert pm._vision_mode == "direct"
        assert pm._gemini_parallel is True
        assert pm._gemini_base_url == ""
        assert pm._gemini_model == ""

    def test_モード設定(self):
        pm = ProviderManager()
        pm.configure_vision(mode="off")
        assert pm._vision_mode == "off"

    def test_部分更新(self):
        pm = ProviderManager()
        pm.configure_vision(parallel=False)
        assert pm._gemini_parallel is False
        assert pm._vision_mode == "direct"  # 他は変わらない

    def test_全設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            base_url="http://test",
            api_key="key",
            model="model",
            parallel=False,
            disable_thinking=False,
            coordinate_mode="normalized",
        )
        assert pm._vision_mode == "direct"
        assert pm._gemini_base_url == "http://test"
        assert pm._gemini_api_key == "key"
        assert pm._gemini_model == "model"
        assert pm._gemini_parallel is False
        assert pm._gemini_disable_thinking is False
        assert pm._vision_coordinate_mode == "normalized"

    def test_接続設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            base_url="http://gemini-server",
            api_key="gemini-key",
            model="gemini-model",
            disable_thinking=False,
        )
        assert pm._gemini_base_url == "http://gemini-server"
        assert pm._gemini_api_key == "gemini-key"
        assert pm._gemini_model == "gemini-model"
        assert pm._gemini_disable_thinking is False

    def test_プロンプト設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            system_prompt="共通プロンプト",
            game_prompt="ゲーム別プロンプト",
        )
        assert pm._gemini_system_prompt == "共通プロンプト"
        assert pm._gemini_game_prompt == "ゲーム別プロンプト"


class TestGetVisionProvider:
    """get_vision_provider() のテスト。"""

    def test_offの場合None(self):
        pm = ProviderManager()
        pm.configure_vision(mode="off")
        assert pm.get_vision_provider() is None

    def test_directの場合Provider返却(self):
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            base_url="http://localhost",
            model="test",
        )
        provider = pm.get_vision_provider()
        assert provider is not None
        assert provider.is_available() is True

    def test_設定が反映される(self):
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            base_url="http://gemini",
            api_key="key",
            model="model",
        )
        provider = pm.get_vision_provider()
        assert provider is not None
        assert provider._client.base_url == "http://gemini"
        assert provider._client.api_key == "key"
        assert provider._client.model == "model"

    def test_キャッシュ(self):
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            base_url="http://localhost",
            model="test",
        )
        p1 = pm.get_vision_provider()
        p2 = pm.get_vision_provider()
        assert p1 is p2  # 同一インスタンス


class TestToOriginalPixelCoordinates:
    """_to_original_pixel_coordinates() の座標変換テスト。"""

    def test_pixel_モードリサイズなし(self):
        pm = ProviderManager()
        pm._vision_coordinate_mode = "pixel"
        rect = {"left": 100, "top": 200, "right": 300, "bottom": 400}
        result = pm._to_original_pixel_coordinates(rect, 1280, 800, 1280, 800)
        assert result == {"left": 100, "top": 200, "right": 300, "bottom": 400}

    def test_normalized_モード(self):
        pm = ProviderManager()
        pm._vision_coordinate_mode = "normalized"
        # 500/1000 = 0.5 → 1280 * 0.5 = 640
        rect = {"left": 0, "top": 0, "right": 500, "bottom": 500}
        result = pm._to_original_pixel_coordinates(rect, 1280, 800, 1280, 800)
        assert result["right"] == 640
        assert result["bottom"] == 400

    def test_クランプ(self):
        pm = ProviderManager()
        pm._vision_coordinate_mode = "pixel"
        rect = {"left": -10, "top": -10, "right": 2000, "bottom": 2000}
        result = pm._to_original_pixel_coordinates(rect, 1280, 800, 1280, 800)
        assert result["left"] == 0
        assert result["top"] == 0
        assert result["right"] == 1280
        assert result["bottom"] == 800


class TestPreflightVisionCheck:
    """preflight_vision_check() のテスト。"""

    def test_offモード(self):
        import asyncio
        pm = ProviderManager()
        pm.configure_vision(mode="off")
        result = asyncio.get_event_loop().run_until_complete(pm.preflight_vision_check())
        assert result["ok"] is False
        assert "設定" in result["message"]

    def test_offモード_mode引数でバイパス(self):
        """mode引数を指定すると、_vision_mode=offでも一時Providerでpreflight検証できる"""
        import asyncio
        pm = ProviderManager()
        pm.configure_vision(
            mode="off",
            base_url="http://localhost",
            model="test",
        )
        # mode引数なしだとFalse（offなので）
        result_without = asyncio.get_event_loop().run_until_complete(pm.preflight_vision_check())
        assert result_without["ok"] is False
        # mode引数ありだとProviderは生成される
        result_with = asyncio.get_event_loop().run_until_complete(pm.preflight_vision_check(mode="direct"))
        assert "Vision Providerが設定されていません" not in result_with.get("message", "")

    def test_未設定provider(self):
        import asyncio
        pm = ProviderManager()
        # base_url も model も未設定 → is_available() == False
        result = asyncio.get_event_loop().run_until_complete(pm.preflight_vision_check())
        assert result["ok"] is False


def _build_pm_with_fallback(primary="gemini-primary", fallback="gemini-fallback"):
    """フォールバックテスト用の ProviderManager + mocked VisionProvider を返す。"""
    pm = ProviderManager()
    pm.configure_vision(
        mode="direct",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="dummy",
        model=primary,
        fallback_model=fallback,
    )

    # VisionProvider をまるごとモック
    fake_provider = MagicMock()
    fake_provider.is_available = MagicMock(return_value=True)
    fake_provider.configure = MagicMock()
    fake_provider.direct_translate = AsyncMock()
    pm._vision_provider = fake_provider
    return pm, fake_provider


class TestFallbackLoop:
    """_translate_with_fallback / recognize_and_translate のテスト。"""

    def test_Primary成功ならFallback呼ばない(self):
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.return_value = (
            [{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}],
            "pixel",
        )
        result = asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        assert result is not None
        assert fake.direct_translate.await_count == 1
        # Primary model で設定された
        assert fake.configure.call_args_list[0].kwargs["model"] == "gemini-primary"

    def test_Primary_503_Fallback成功(self):
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.side_effect = [
            NetworkError("Gemini API returned status 503"),
            ([{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}], "pixel"),
        ]
        result = asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        assert result is not None
        assert fake.direct_translate.await_count == 2
        # Primary → Fallback
        models_used = [c.kwargs["model"] for c in fake.configure.call_args_list]
        assert "gemini-primary" in models_used
        assert "gemini-fallback" in models_used

    def test_両方503でNetworkError(self):
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.side_effect = NetworkError("Gemini API returned status 503")
        with pytest.raises(NetworkError):
            asyncio.get_event_loop().run_until_complete(
                pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
            )
        assert fake.direct_translate.await_count == 2

    def test_Fallback未設定で503ならNetworkError(self):
        pm, fake = _build_pm_with_fallback(fallback="")  # Fallback 無し
        fake.direct_translate.side_effect = NetworkError("Gemini API returned status 503")
        with pytest.raises(NetworkError):
            asyncio.get_event_loop().run_until_complete(
                pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
            )
        # Primary のみで試行終了
        assert fake.direct_translate.await_count == 1

    def test_Circuit_OPEN中はPrimaryスキップ(self):
        pm, fake = _build_pm_with_fallback()
        # サーキットを強制的に OPEN に
        pm._circuit = CircuitBreaker(threshold=1, window_sec=300, open_sec=300)
        pm._circuit.record_failure()
        assert pm._circuit.get_state() == "open"

        fake.direct_translate.return_value = (
            [{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}],
            "pixel",
        )
        result = asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        assert result is not None
        # Primary は呼ばれず Fallback のみ
        assert fake.direct_translate.await_count == 1
        assert fake.configure.call_args_list[0].kwargs["model"] == "gemini-fallback"

    def test_Primary_503_3回でCircuitがOPEN(self):
        pm, fake = _build_pm_with_fallback()
        # Fallback も失敗にしておく（Primary の失敗カウントが記録されるか確認）
        fake.direct_translate.side_effect = NetworkError("Gemini API returned status 503")

        for _ in range(3):
            with pytest.raises(NetworkError):
                asyncio.get_event_loop().run_until_complete(
                    pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
                )

        # 3回の Primary 失敗で OPEN に遷移
        assert pm._circuit.get_state() == "open"

    def test_ApiKeyErrorはFallbackしない(self):
        from py_modules.providers.base import ApiKeyError
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.side_effect = ApiKeyError("invalid")
        with pytest.raises(ApiKeyError):
            asyncio.get_event_loop().run_until_complete(
                pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
            )
        # Primary だけで終了
        assert fake.direct_translate.await_count == 1

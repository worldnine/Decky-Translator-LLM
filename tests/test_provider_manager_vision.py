# tests/test_provider_manager_vision.py
# ProviderManager のVision関連テスト

import pytest
from py_modules.providers import ProviderManager


class TestConfigureVision:
    """configure_vision() のテスト。"""

    def test_デフォルト設定(self):
        pm = ProviderManager()
        assert pm._vision_mode == "off"
        assert pm._vision_llm_parallel is True
        assert pm._vision_assist_confidence_threshold == 0.95
        assert pm._vision_assist_send_all is False

    def test_モード設定(self):
        pm = ProviderManager()
        pm.configure_vision(mode="assist")
        assert pm._vision_mode == "assist"

    def test_部分更新(self):
        pm = ProviderManager()
        pm.configure_vision(parallel=False)
        assert pm._vision_llm_parallel is False
        assert pm._vision_mode == "off"  # 他は変わらない

    def test_全設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            parallel=False,
            assist_send_all=True,
            assist_confidence_threshold=0.8,
            coordinate_mode="normalized",
        )
        assert pm._vision_mode == "direct"
        assert pm._vision_llm_parallel is False
        assert pm._vision_assist_send_all is True
        assert pm._vision_assist_confidence_threshold == 0.8
        assert pm._vision_coordinate_mode == "normalized"

    def test_Vision_LLM接続設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            base_url="http://vision-server",
            api_key="vision-key",
            model="vision-model",
            disable_thinking=False,
        )
        assert pm._vision_llm_base_url == "http://vision-server"
        assert pm._vision_llm_api_key == "vision-key"
        assert pm._vision_llm_model == "vision-model"
        assert pm._vision_llm_disable_thinking is False

    def test_Vision_LLMプロンプト設定(self):
        pm = ProviderManager()
        pm.configure_vision(
            system_prompt="vision common",
            game_prompt="vision game",
        )
        assert pm._vision_llm_system_prompt == "vision common"
        assert pm._vision_llm_game_prompt == "vision game"


class TestConfigureTextLlm:
    """configure_text_llm() のテスト。"""

    def test_デフォルト設定(self):
        pm = ProviderManager()
        assert pm._text_llm_base_url == ""
        assert pm._text_llm_model == ""
        assert pm._text_llm_parallel is True

    def test_全設定(self):
        pm = ProviderManager()
        pm.configure_text_llm(
            base_url="http://text-server",
            api_key="text-key",
            model="text-model",
            system_prompt="text system",
            game_prompt="text game",
            disable_thinking=False,
            parallel=False,
        )
        assert pm._text_llm_base_url == "http://text-server"
        assert pm._text_llm_api_key == "text-key"
        assert pm._text_llm_model == "text-model"
        assert pm._text_llm_system_prompt == "text system"
        assert pm._text_llm_game_prompt == "text game"
        assert pm._text_llm_disable_thinking is False
        assert pm._text_llm_parallel is False

    def test_後方互換エイリアス(self):
        """configure_llm() がconfigure_text_llm() と同じ動作をする"""
        pm = ProviderManager()
        pm.configure_llm(base_url="http://test", model="m1")
        assert pm._text_llm_base_url == "http://test"
        assert pm._text_llm_model == "m1"


class TestTextVisionSeparation:
    """Text LLMとVision LLMの設定分離テスト。"""

    def test_独立した設定(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://text", model="text-m")
        pm.configure_vision(base_url="http://vision", model="vision-m")
        assert pm._text_llm_base_url == "http://text"
        assert pm._text_llm_model == "text-m"
        assert pm._vision_llm_base_url == "http://vision"
        assert pm._vision_llm_model == "vision-m"

    def test_Vision未設定時はText_LLMフォールバック(self):
        pm = ProviderManager()
        pm.configure_text_llm(
            base_url="http://text-server",
            api_key="text-key",
            model="text-model",
        )
        pm.configure_vision(mode="direct")
        provider = pm.get_vision_provider()
        assert provider is not None
        # Vision LLM未設定なのでText LLMにフォールバック
        assert provider._client.base_url == "http://text-server"
        assert provider._client.api_key == "text-key"
        assert provider._client.model == "text-model"

    def test_Vision設定がText_LLMに影響しない(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://text", model="text-m")
        pm.configure_vision(
            mode="direct",
            base_url="http://vision",
            model="vision-m",
        )
        # Text LLMは変わらない
        assert pm._text_llm_base_url == "http://text"
        assert pm._text_llm_model == "text-m"


class TestGetVisionProvider:
    """get_vision_provider() のテスト。"""

    def test_offの場合None(self):
        pm = ProviderManager()
        pm.configure_vision(mode="off")
        assert pm.get_vision_provider() is None

    def test_assistの場合Provider返却(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://localhost", model="test")
        pm.configure_vision(mode="assist")
        provider = pm.get_vision_provider()
        assert provider is not None
        assert provider.is_available() is True

    def test_Text_LLM設定フォールバック(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://llm-server", api_key="llm-key", model="llm-model")
        pm.configure_vision(mode="direct")
        provider = pm.get_vision_provider()
        assert provider is not None
        assert provider._client.base_url == "http://llm-server"
        assert provider._client.api_key == "llm-key"
        assert provider._client.model == "llm-model"

    def test_Vision専用設定が優先(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://text", api_key="text-key", model="text-m")
        pm.configure_vision(
            mode="direct",
            base_url="http://vision",
            api_key="vision-key",
            model="vision-m",
        )
        provider = pm.get_vision_provider()
        assert provider is not None
        assert provider._client.base_url == "http://vision"
        assert provider._client.api_key == "vision-key"
        assert provider._client.model == "vision-m"

    def test_キャッシュ(self):
        pm = ProviderManager()
        pm.configure_text_llm(base_url="http://localhost", model="test")
        pm.configure_vision(mode="direct")
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

    def test_未設定provider(self):
        import asyncio
        pm = ProviderManager()
        pm.configure_vision(mode="direct")
        # LLM設定もVision設定もない → is_available() == False
        result = asyncio.get_event_loop().run_until_complete(pm.preflight_vision_check())
        assert result["ok"] is False

# tests/test_prompt_injection.py
# プロンプト合成と注入経路のテスト — Gemini Vision専用構成

import pytest
from py_modules.providers.gemini_vision import GeminiVisionProvider


class TestVisionAssistPromptInjection:
    """Vision Assist プロンプトの注入順テスト。
    注入順: Vision Assist固定 → 共通Vision → ゲーム別Vision"""

    def _make_provider(self, custom_prompt="", game_prompt=""):
        p = GeminiVisionProvider(
            base_url="http://test",
            model="test",
            custom_prompt=custom_prompt,
            game_prompt=game_prompt,
        )
        return p

    def test_固定プロンプトのみ(self):
        p = self._make_provider()
        # _build_additional_prompt が空なら追加指示なし
        additional = p._build_additional_prompt()
        assert additional == ""

    def test_共通Visionプロンプト注入(self):
        p = self._make_provider(custom_prompt="画面端UIを無視")
        additional = p._build_additional_prompt()
        assert "画面端UIを無視" in additional

    def test_ゲーム別Visionプロンプト注入(self):
        p = self._make_provider(game_prompt="会話窓を優先")
        additional = p._build_additional_prompt()
        assert "会話窓を優先" in additional

    def test_共通とゲーム別の両方(self):
        p = self._make_provider(
            custom_prompt="共通Vision",
            game_prompt="ゲームVision",
        )
        additional = p._build_additional_prompt()
        assert "共通Vision" in additional
        assert "ゲームVision" in additional
        # 共通が先、ゲーム別が後
        assert additional.index("共通Vision") < additional.index("ゲームVision")

    def test_Assist固定プロンプトにゲーム依存ルールがない(self):
        """Assist固定プロンプトに「略語保持リスト」等が残っていないこと"""
        p = self._make_provider()
        additional = p._build_additional_prompt()
        assert "HP, MP" not in additional


class TestVisionDirectPromptInjection:
    """Vision Direct プロンプトの注入順テスト。
    注入順: Vision Direct固定 → 共通Vision → ゲーム別Vision"""

    def test_共通とゲーム別プロンプトが分離注入される(self):
        """configure_vision で共通/ゲーム別プロンプトが正しく保持される"""
        from py_modules.providers import ProviderManager
        pm = ProviderManager()
        pm.configure_vision(
            mode="direct",
            base_url="http://vision",
            model="vision-m",
            system_prompt="Vision共通指示",
            game_prompt="Visionゲーム指示",
        )
        assert pm._gemini_system_prompt == "Vision共通指示"
        assert pm._gemini_game_prompt == "Visionゲーム指示"


class TestPreflightPromptIsolation:
    """preflight が可変プロンプトの影響を受けないテスト。"""

    def test_preflightに共通プロンプトが入らない(self):
        """preflight_check() は固定プロンプトのみ使用し、
        共通/ゲーム別プロンプトが注入されないこと"""
        p = GeminiVisionProvider(
            base_url="http://test",
            model="test",
            custom_prompt="この指示はpreflightに入ってはいけない",
            game_prompt="このゲーム指示もpreflightに入ってはいけない",
        )
        # preflight_check はsystemプロンプトに固定文字列のみを使う
        # _build_additional_prompt() を使っていないことを確認
        import inspect
        source = inspect.getsource(p.preflight_check)
        assert "_build_additional_prompt" not in source
        assert "_custom_prompt" not in source
        assert "_game_prompt" not in source

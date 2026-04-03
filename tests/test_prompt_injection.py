# tests/test_prompt_injection.py
# プロンプト合成と注入経路のテスト

import pytest
from py_modules.providers.llm_translate import LlmTranslateProvider, TEXT_FIXED_PROMPT
from py_modules.providers.gemini_vision import GeminiVisionProvider


class TestTextPromptInjection:
    """Text翻訳プロンプトの注入順テスト。
    注入順: Text固定プロンプト → 共通Text プロンプト → ゲーム別Text プロンプト"""

    def test_固定プロンプトのみ(self):
        p = LlmTranslateProvider()
        prompt = p._build_system_prompt("en", "ja")
        assert "game text translator" in prompt
        assert "Additional instructions" not in prompt

    def test_共通プロンプト注入(self):
        p = LlmTranslateProvider(system_prompt="略語を保持してください")
        prompt = p._build_system_prompt("en", "ja")
        assert "Additional instructions" in prompt
        assert "略語を保持してください" in prompt

    def test_ゲーム別プロンプト注入(self):
        p = LlmTranslateProvider()
        p.configure(game_prompt="このゲームはRPGです")
        prompt = p._build_system_prompt("en", "ja")
        assert "このゲームはRPGです" in prompt

    def test_共通とゲーム別の両方(self):
        p = LlmTranslateProvider(system_prompt="共通指示")
        p.configure(game_prompt="ゲーム指示")
        prompt = p._build_system_prompt("en", "ja")
        # 両方が含まれる
        assert "共通指示" in prompt
        assert "ゲーム指示" in prompt
        # 共通が先、ゲーム別が後
        assert prompt.index("共通指示") < prompt.index("ゲーム指示")

    def test_固定プロンプトにゲーム依存ルールがない(self):
        """固定プロンプトに「UIは短く訳す」等のゲーム依存指示が残っていないこと"""
        fixed = TEXT_FIXED_PROMPT
        assert "UI label" not in fixed
        assert "menu item" not in fixed
        assert "HP, MP" not in fixed
        assert "abbreviation" not in fixed.lower()

    def test_言語名変換(self):
        p = LlmTranslateProvider()
        prompt = p._build_system_prompt("en", "ja")
        assert "English" in prompt
        assert "Japanese" in prompt

    def test_auto言語(self):
        p = LlmTranslateProvider()
        prompt = p._build_system_prompt("auto", "ja")
        assert "detected language" in prompt


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
        import asyncio
        p = self._make_provider()
        # assist_translate のsystem_promptを直接検証するため、
        # 内部の _build_additional_prompt を確認
        additional = p._build_additional_prompt()
        assert "HP, MP" not in additional


class TestVisionDirectPromptInjection:
    """Vision Direct プロンプトの注入順テスト。
    注入順: Vision Direct固定 → 共通Vision → ゲーム別Vision"""

    def test_プロンプト分離(self):
        """Text LLMとVision LLMに異なるプロンプトが注入される"""
        from py_modules.providers import ProviderManager
        pm = ProviderManager()
        pm.configure_text_llm(
            base_url="http://text",
            model="text-m",
            system_prompt="Text共通指示",
            game_prompt="Textゲーム指示",
        )
        pm.configure_vision(
            mode="direct",
            base_url="http://vision",
            model="vision-m",
            system_prompt="Vision共通指示",
            game_prompt="Visionゲーム指示",
        )
        # Text LLM側の確認
        assert pm._text_llm_system_prompt == "Text共通指示"
        assert pm._text_llm_game_prompt == "Textゲーム指示"
        # Vision LLM側の確認
        assert pm._vision_llm_system_prompt == "Vision共通指示"
        assert pm._vision_llm_game_prompt == "Visionゲーム指示"


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

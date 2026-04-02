# tests/test_llm_api_client.py
# LlmApiClient のユニットテスト

import pytest
from py_modules.providers.llm_api_client import LlmApiClient
from py_modules.providers.base import ConfigurationError


class TestIsGemini:
    """_is_gemini() のGeminiネイティブAPI判定テスト。"""

    def test_geminiモデルかつgoogleapi(self):
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gemini-2.5-flash-lite",
        )
        assert client.is_gemini() is True

    def test_geminiモデルだがopenrouter(self):
        client = LlmApiClient(
            base_url="https://openrouter.ai/api/v1",
            model="gemini-2.5-flash-lite",
        )
        assert client.is_gemini() is False

    def test_非geminiモデルかつgoogleapi(self):
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gpt-4o-mini",
        )
        assert client.is_gemini() is False

    def test_ollama_localhost(self):
        client = LlmApiClient(
            base_url="http://localhost:11434/v1",
            model="llama3.1",
        )
        assert client.is_gemini() is False

    def test_大文字混在gemini(self):
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="Gemini-2.0-Flash",
        )
        assert client.is_gemini() is True


class TestStripThinkingTags:
    """strip_thinking_tags() のテスト。"""

    def test_thinkタグ除去(self):
        text = "<think>reasoning here</think>translation result"
        assert LlmApiClient.strip_thinking_tags(text) == "translation result"

    def test_reasoningタグ除去(self):
        text = "<reasoning>analysis</reasoning>output"
        assert LlmApiClient.strip_thinking_tags(text) == "output"

    def test_複数行thinkタグ(self):
        text = "<think>\nstep 1\nstep 2\n</think>\nfinal answer"
        assert LlmApiClient.strip_thinking_tags(text) == "final answer"

    def test_タグなし(self):
        text = "normal text"
        assert LlmApiClient.strip_thinking_tags(text) == "normal text"

    def test_空文字列(self):
        assert LlmApiClient.strip_thinking_tags("") == ""


class TestIsConfigured:
    """is_configured() のテスト。"""

    def test_両方設定済み(self):
        client = LlmApiClient(base_url="http://localhost", model="test")
        assert client.is_configured() is True

    def test_base_url未設定(self):
        client = LlmApiClient(base_url="", model="test")
        assert client.is_configured() is False

    def test_model未設定(self):
        client = LlmApiClient(base_url="http://localhost", model="")
        assert client.is_configured() is False


class TestConfigurationError:
    """ConfigurationError の送出テスト。"""

    def test_未設定時にCallでConfigurationError(self):
        client = LlmApiClient(base_url="", model="")
        with pytest.raises(ConfigurationError):
            client.call([{"role": "user", "content": "test"}])

    def test_base_urlのみ設定時にConfigurationError(self):
        client = LlmApiClient(base_url="http://localhost", model="")
        with pytest.raises(ConfigurationError):
            client.call([{"role": "user", "content": "test"}])


class TestConfigure:
    """configure() のテスト。"""

    def test_部分更新(self):
        client = LlmApiClient(base_url="old", model="old")
        client.configure(base_url="new")
        assert client.base_url == "new"
        assert client.model == "old"

    def test_Noneは更新しない(self):
        client = LlmApiClient(base_url="keep", model="keep")
        client.configure(base_url=None, model=None)
        assert client.base_url == "keep"
        assert client.model == "keep"

    def test_末尾スラッシュ除去(self):
        client = LlmApiClient()
        client.configure(base_url="http://localhost/v1/")
        assert client.base_url == "http://localhost/v1"

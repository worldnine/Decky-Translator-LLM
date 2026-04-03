# tests/test_gemini_vision.py
# GeminiVisionProvider のユニットテスト

import json
import pytest
from py_modules.providers.gemini_vision import GeminiVisionProvider


class TestExtractJson:
    """_extract_json() のJSONパーステスト。"""

    def test_正常なJSON(self):
        text = '{"regions": [{"text": "Hello"}]}'
        result = GeminiVisionProvider._extract_json(text)
        assert result == {"regions": [{"text": "Hello"}]}

    def test_マークダウンコードブロック(self):
        text = '```json\n{"regions": []}\n```'
        result = GeminiVisionProvider._extract_json(text)
        assert result == {"regions": []}

    def test_ゴミテキスト付き(self):
        text = 'Here is the result:\n{"regions": [{"text": "test"}]}\nDone.'
        result = GeminiVisionProvider._extract_json(text)
        assert result["regions"][0]["text"] == "test"

    def test_配列直返し(self):
        text = '[{"text": "a"}, {"text": "b"}]'
        result = GeminiVisionProvider._extract_json(text)
        assert len(result) == 2

    def test_thinkingタグ付き(self):
        text = '<think>analysis</think>{"regions": []}'
        result = GeminiVisionProvider._extract_json(text)
        assert result == {"regions": []}

    def test_パース不能(self):
        with pytest.raises(json.JSONDecodeError):
            GeminiVisionProvider._extract_json("not json at all")


class TestRecoverTruncatedJson:
    """_recover_truncated_json() の部分回復テスト。"""

    def test_途切れたregions(self):
        # 2番目のregionが完了した直後で途切れたケース（},の後にさらに途切れ）
        text = ('{"coordinate_mode":"normalized_0_1000","regions":['
                '{"text":"Hello","translated_text":"こんにちは","rect":{"left":100,"top":200,"right":300,"bottom":250}},'
                '{"text":"World","translated_text":"世界","rect":{"left":400,"top":200,"right":600,"bottom":250}},'
                '{"text":"trunca')
        result = GeminiVisionProvider._recover_truncated_json(text)
        assert result is not None
        regions = result.get("regions", [])
        assert len(regions) == 2
        assert regions[0]["text"] == "Hello"
        assert regions[1]["text"] == "World"

    def test_完全なJSON(self):
        text = '{"regions": [{"text": "a"}]}'
        result = GeminiVisionProvider._recover_truncated_json(text)
        assert result is not None
        assert len(result["regions"]) == 1

    def test_回復不能(self):
        result = GeminiVisionProvider._recover_truncated_json("totally broken")
        assert result is None

    def test_空文字列(self):
        result = GeminiVisionProvider._recover_truncated_json("")
        assert result is None


class TestGenerateTestPng:
    """_generate_test_png_base64() のテスト。"""

    def test_有効なbase64(self):
        import base64
        b64 = GeminiVisionProvider._generate_test_png_base64()
        assert len(b64) > 0
        # デコードしてPNGシグネチャ確認
        raw = base64.b64decode(b64)
        assert raw[:8] == b'\x89PNG\r\n\x1a\n'


class TestGeminiVisionProviderConfig:
    """GeminiVisionProvider の設定テスト。"""

    def test_初期状態で利用不可(self):
        provider = GeminiVisionProvider()
        assert provider.is_available() is False

    def test_設定後に利用可能(self):
        provider = GeminiVisionProvider(
            base_url="http://localhost:8080",
            model="test-model",
        )
        assert provider.is_available() is True

    def test_configure部分更新(self):
        provider = GeminiVisionProvider(
            base_url="http://old",
            model="old",
        )
        provider.configure(base_url="http://new")
        assert provider._client.base_url == "http://new"
        assert provider._client.model == "old"

    def test_name(self):
        provider = GeminiVisionProvider(model="gemini-2.5-flash")
        assert "gemini-2.5-flash" in provider.name

    def test_preflight未設定(self):
        import asyncio
        provider = GeminiVisionProvider()
        ok, msg = asyncio.get_event_loop().run_until_complete(provider.preflight_check())
        assert ok is False
        assert "設定" in msg

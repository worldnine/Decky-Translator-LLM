# tests/test_llm_batch_parse.py
# LLMバッチ翻訳のレスポンスパース処理のユニットテスト

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from py_modules.providers.llm_translate import LlmTranslateProvider


@pytest.fixture
def provider():
    return LlmTranslateProvider(
        base_url="http://localhost:11434",
        api_key="test-key",
        model="test-model",
    )


# ===== _parse_batch_response のテスト =====


class TestParseBatchResponse:
    """番号ベースパースの各種パターンをテスト。"""

    def test_正常な番号付きレスポンス(self, provider):
        response = "[1] こんにちは\n[2] さようなら\n[3] ありがとう"
        result = provider._parse_batch_response(response, 3)
        assert result == ["こんにちは", "さようなら", "ありがとう"]

    def test_番号が1つ欠落(self, provider):
        response = "[1] こんにちは\n[3] ありがとう"
        result = provider._parse_batch_response(response, 3)
        assert result == ["こんにちは", None, "ありがとう"]

    def test_空行が含まれる(self, provider):
        response = "[1] こんにちは\n\n[2] さようなら\n\n[3] ありがとう"
        result = provider._parse_batch_response(response, 3)
        assert result == ["こんにちは", "さようなら", "ありがとう"]

    def test_LLMが改行で翻訳を分割したケース(self, provider):
        """番号なし行は直前の番号の続きとして結合される。"""
        response = "[1] これは長い\n翻訳テキストです\n[2] 短い"
        result = provider._parse_batch_response(response, 2)
        assert result == ["これは長い 翻訳テキストです", "短い"]

    def test_ゲームテキストの角括弧と衝突しない(self, provider):
        """[System] のような非数字の角括弧は番号として扱わない。"""
        response = "[1] [System] メッセージを受信しました\n[2] HP: 100"
        result = provider._parse_batch_response(response, 2)
        assert result == ["[System] メッセージを受信しました", "HP: 100"]

    def test_範囲外の番号は無視(self, provider):
        response = "[0] 無効\n[1] 有効\n[2] 有効\n[99] 無効"
        result = provider._parse_batch_response(response, 2)
        assert result == ["有効", "有効"]

    def test_全て欠落(self, provider):
        """番号が全く含まれないレスポンス。"""
        response = "こんにちは\nさようなら"
        result = provider._parse_batch_response(response, 2)
        assert result == [None, None]

    def test_テキスト1件のみ(self, provider):
        response = "[1] 翻訳結果"
        result = provider._parse_batch_response(response, 1)
        assert result == ["翻訳結果"]

    def test_前後の空白を除去(self, provider):
        response = "  [1]  こんにちは  \n  [2]  さようなら  "
        result = provider._parse_batch_response(response, 2)
        assert result == ["こんにちは", "さようなら"]

    def test_同じ番号が複数回出たら後勝ち(self, provider):
        response = "[1] 最初\n[1] 修正版\n[2] テスト"
        result = provider._parse_batch_response(response, 2)
        assert result == ["修正版", "テスト"]

    def test_空レスポンス(self, provider):
        response = ""
        result = provider._parse_batch_response(response, 2)
        assert result == [None, None]

    def test_thinking_tags_が除去済みの前提(self, provider):
        """_strip_thinking_tags は _call_api 内で呼ばれるため、
        _parse_batch_response に渡されるときはクリーン。"""
        response = "[1] 翻訳A\n[2] 翻訳B"
        result = provider._parse_batch_response(response, 2)
        assert result == ["翻訳A", "翻訳B"]


# ===== translate_batch の統合テスト =====


class TestTranslateBatch:
    """translate_batch の欠落補完ロジックをテスト。"""

    def test_全件成功でそのまま返す(self, provider):
        with patch.object(provider._client, "call", return_value="[1] A\n[2] B"):
            result = asyncio.get_event_loop().run_until_complete(
                provider.translate_batch(["x", "y"], "en", "ja")
            )
        assert result == ["A", "B"]

    def test_欠落分だけ個別翻訳で補完(self, provider):
        # バッチでは [2] が欠落
        with patch.object(provider._client, "call", return_value="[1] A\n[3] C") as mock_api:
            # 個別翻訳時の _call_api 呼び出し
            def side_effect(messages, temperature=0.1):
                # 最初の呼び出しはバッチ
                if mock_api.call_count == 1:
                    return "[1] A\n[3] C"
                # 2回目は個別翻訳（テキスト "y" → "B"）
                return "B"

            mock_api.side_effect = side_effect

            result = asyncio.get_event_loop().run_until_complete(
                provider.translate_batch(["x", "y", "z"], "en", "ja")
            )
        assert result == ["A", "B", "C"]

    def test_個別翻訳も失敗したら原文を返す(self, provider):
        with patch.object(provider._client, "call") as mock_api:
            def side_effect(messages, temperature=0.1):
                if mock_api.call_count == 1:
                    return "[1] A"  # [2] 欠落
                raise Exception("API error")

            mock_api.side_effect = side_effect

            result = asyncio.get_event_loop().run_until_complete(
                provider.translate_batch(["x", "y"], "en", "ja")
            )
        assert result == ["A", "y"]  # 欠落分は原文

    def test_バッチAPI自体がエラーなら全件個別翻訳(self, provider):
        # 並列実行だと呼び出し順が不定なため、テスト用に逐次モードにする
        provider._parallel = False
        call_count = 0

        with patch.object(provider._client, "call") as mock_api:
            def side_effect(messages, temperature=0.1):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise Exception("Batch API error")
                # 個別翻訳
                return f"translated_{call_count - 1}"

            mock_api.side_effect = side_effect

            result = asyncio.get_event_loop().run_until_complete(
                provider.translate_batch(["a", "b"], "en", "ja")
            )
        assert result == ["translated_1", "translated_2"]
        provider._parallel = True  # 復元

    def test_テキスト1件なら単一翻訳を使う(self, provider):
        with patch.object(provider._client, "call", return_value="翻訳結果"):
            result = asyncio.get_event_loop().run_until_complete(
                provider.translate_batch(["hello"], "en", "ja")
            )
        assert result == ["翻訳結果"]

    def test_空リスト(self, provider):
        result = asyncio.get_event_loop().run_until_complete(
            provider.translate_batch([], "en", "ja")
        )
        assert result == []

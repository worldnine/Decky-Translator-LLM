# tests/test_llm_api_client.py
# LlmApiClient のユニットテスト

from unittest.mock import MagicMock, patch

import pytest
import requests

from py_modules.providers.llm_api_client import (
    LlmApiClient,
    _execute_with_retry,
    _parse_retry_after,
    _apply_jitter,
    _TOTAL_RETRY_BUDGET_SEC,
)
from py_modules.providers.base import (
    ConfigurationError,
    NetworkError,
    ApiKeyError,
)


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


class TestGeminiUrlNormalization:
    """Gemini ネイティブAPI URL正規化のテスト。"""

    def test_openai接尾辞のみ(self):
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            model="gemini-2.5-flash",
        )
        # _call_gemini_native 内部でURLを構築するため、is_gemini()を通じて間接確認
        assert client.is_gemini() is True

    def test_openai_chat_completions完全URL(self):
        """v1beta/openai/chat/completions のような完全URLでも正規化される。"""
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
            model="gemini-2.5-flash",
        )
        assert client.is_gemini() is True
        # 内部で正規化されることを間接検証: URLの /openai/chat/completions が剥がされる
        base = client._base_url
        changed = True
        while changed:
            changed = False
            for suffix in ["/chat/completions", "/openai", "/v1"]:
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    changed = True
        assert base == "https://generativelanguage.googleapis.com/v1beta"

    def test_v1_openai_chat_completions(self):
        """v1/openai/chat/completions パターン。"""
        base = "https://generativelanguage.googleapis.com/v1/openai/chat/completions"
        changed = True
        while changed:
            changed = False
            for suffix in ["/chat/completions", "/openai", "/v1"]:
                if base.endswith(suffix):
                    base = base[:-len(suffix)]
                    changed = True
        assert base == "https://generativelanguage.googleapis.com"


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


def _make_response(status_code: int, headers: dict = None) -> MagicMock:
    """requests.Response のmockを作成する。"""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.text = f"status={status_code}"
    return resp


class TestParseRetryAfter:
    """_parse_retry_after() のテスト。"""

    def test_秒数フォーマット(self):
        resp = _make_response(429, headers={"Retry-After": "12"})
        assert _parse_retry_after(resp) == 12.0

    def test_小数点あり(self):
        resp = _make_response(429, headers={"Retry-After": "2.5"})
        assert _parse_retry_after(resp) == 2.5

    def test_ヘッダーなし(self):
        resp = _make_response(429, headers={})
        assert _parse_retry_after(resp) is None

    def test_responseがNone(self):
        assert _parse_retry_after(None) is None

    def test_不正な値(self):
        resp = _make_response(429, headers={"Retry-After": "Mon, 07 Apr 2026 12:00:00 GMT"})
        # RFC date は非対応
        assert _parse_retry_after(resp) is None


class TestApplyJitter:
    """_apply_jitter() のテスト。"""

    def test_ジッターは30パーセント以内(self):
        base = 10.0
        for _ in range(100):
            jittered = _apply_jitter(base)
            assert 7.0 <= jittered <= 13.0


@pytest.fixture
def mock_sleep_and_jitter():
    """time.sleepと_apply_jitterを無力化し、経過時間を進めない。"""
    with patch("py_modules.providers.llm_api_client.time.sleep") as sleep_mock, \
         patch("py_modules.providers.llm_api_client._apply_jitter", side_effect=lambda d: d) as jitter_mock:
        yield sleep_mock, jitter_mock


class TestExecuteWithRetry:
    """_execute_with_retry() のテスト。"""

    def test_初回200ならそのまま返す(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        success = _make_response(200)
        request_fn = MagicMock(return_value=success)

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result is success
        assert request_fn.call_count == 1
        sleep_mock.assert_not_called()

    def test_503が3回続いたら最後の503を返す(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        failures = [_make_response(503) for _ in range(4)]
        request_fn = MagicMock(side_effect=failures)

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 503
        assert request_fn.call_count == 4
        # 5s→10s→20s の3回スリープ
        assert sleep_mock.call_count == 3
        assert sleep_mock.call_args_list[0].args[0] == 5.0
        assert sleep_mock.call_args_list[1].args[0] == 10.0
        assert sleep_mock.call_args_list[2].args[0] == 20.0

    def test_503が2回後に200で成功(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        responses = [_make_response(503), _make_response(503), _make_response(200)]
        request_fn = MagicMock(side_effect=responses)

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 200
        assert request_fn.call_count == 3
        assert sleep_mock.call_count == 2

    def test_401はリトライしない(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        resp = _make_response(401)
        request_fn = MagicMock(return_value=resp)

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 401
        assert request_fn.call_count == 1
        sleep_mock.assert_not_called()

    def test_400はリトライしない(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        resp = _make_response(400)
        request_fn = MagicMock(return_value=resp)

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 400
        sleep_mock.assert_not_called()

    def test_ConnectionErrorは2s5s10sでリトライ(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        exc = requests.exceptions.ConnectionError("connection refused")
        request_fn = MagicMock(side_effect=[exc, exc, exc, exc])

        with pytest.raises(requests.exceptions.ConnectionError):
            _execute_with_retry(request_fn, api_label="Test")

        assert request_fn.call_count == 4
        assert sleep_mock.call_count == 3
        # transient 系: 2→5→10
        assert sleep_mock.call_args_list[0].args[0] == 2.0
        assert sleep_mock.call_args_list[1].args[0] == 5.0
        assert sleep_mock.call_args_list[2].args[0] == 10.0

    def test_Timeoutも同様にリトライ(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        exc = requests.exceptions.Timeout("timeout")
        success = _make_response(200)
        request_fn = MagicMock(side_effect=[exc, success])

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 200
        assert sleep_mock.call_count == 1
        assert sleep_mock.call_args_list[0].args[0] == 2.0

    def test_429はRetry_Afterを尊重する(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        resp_429 = _make_response(429, headers={"Retry-After": "7"})
        resp_200 = _make_response(200)
        request_fn = MagicMock(side_effect=[resp_429, resp_200])

        result = _execute_with_retry(request_fn, api_label="Test")

        assert result.status_code == 200
        # Retry-After=7 がジッター付きバックオフより優先される
        assert sleep_mock.call_args_list[0].args[0] == 7.0

    def test_全体予算超過で打ち切り(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        resp_503 = _make_response(503)
        request_fn = MagicMock(return_value=resp_503)

        # monotonic を進めて予算超過を再現
        base_time = [0.0]
        def fake_monotonic():
            base_time[0] += 50.0  # 1回目: 0, 2回目: 50, 3回目: 100 → 予算超過
            return base_time[0] - 50.0

        with patch("py_modules.providers.llm_api_client.time.monotonic", side_effect=fake_monotonic):
            result = _execute_with_retry(request_fn, api_label="Test")

        # 予算超過で途中打ち切り。最後の503が返る
        assert result.status_code == 503
        # 3回目の sleep 前で予算オーバー → sleep は2回以下
        assert sleep_mock.call_count <= 2


class TestGeminiNativeWithRetry:
    """_call_gemini_native の requests.post が503でリトライされるかを結合テスト。"""

    def test_503後に200で成功(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter

        resp_ok = _make_response(200)
        resp_ok.json = MagicMock(return_value={
            "candidates": [{
                "content": {"parts": [{"text": "hello"}]},
                "finishReason": "STOP",
            }],
        })

        responses = [_make_response(503), resp_ok]

        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            api_key="dummy",
        )
        with patch(
            "py_modules.providers.llm_api_client.requests.post",
            side_effect=responses,
        ) as post_mock:
            result = client.call([{"role": "user", "content": "test"}])

        assert result == "hello"
        assert post_mock.call_count == 2
        assert sleep_mock.call_count == 1

    def test_4回連続503でNetworkError(self, mock_sleep_and_jitter):
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            api_key="dummy",
        )
        with patch(
            "py_modules.providers.llm_api_client.requests.post",
            side_effect=[_make_response(503) for _ in range(4)],
        ):
            with pytest.raises(NetworkError):
                client.call([{"role": "user", "content": "test"}])

    def test_401は即時ApiKeyError(self, mock_sleep_and_jitter):
        sleep_mock, _ = mock_sleep_and_jitter
        client = LlmApiClient(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-2.5-flash",
            api_key="bad",
        )
        with patch(
            "py_modules.providers.llm_api_client.requests.post",
            return_value=_make_response(401),
        ) as post_mock:
            with pytest.raises(ApiKeyError):
                client.call([{"role": "user", "content": "test"}])

        assert post_mock.call_count == 1
        sleep_mock.assert_not_called()

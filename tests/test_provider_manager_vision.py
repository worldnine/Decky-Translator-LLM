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

    def test_Primary_Timeout_Fallback成功(self):
        """Primary が Timeout 由来 NetworkError を投げたら Fallback に切り替える。
        Timeout もサーキットカウント対象なので failure が増える。"""
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.side_effect = [
            NetworkError("Geminiサーバーがタイムアウトしました"),
            ([{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}], "pixel"),
        ]
        result = asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        assert result is not None
        assert fake.direct_translate.await_count == 2
        # Timeout もサーキット対象
        assert len(pm._circuit._failures) == 1

    def test_Primary_Timeout_3回でCircuitがOPEN(self):
        pm, fake = _build_pm_with_fallback()
        # Primary と Fallback 両方で失敗（Primary の Timeout がカウントされる）
        fake.direct_translate.side_effect = NetworkError(
            "Geminiサーバーがタイムアウトしました"
        )
        for _ in range(3):
            with pytest.raises(NetworkError):
                asyncio.get_event_loop().run_until_complete(
                    pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
                )
        assert pm._circuit.get_state() == "open"

    def test_PrimaryとFallbackのtimeout値が異なる(self):
        """Primary=15s / Fallback=60s が direct_translate に渡されているか。"""
        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.side_effect = [
            NetworkError("Gemini API returned status 503"),
            ([{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}], "pixel"),
        ]
        asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        # 1回目呼び出し: Primary (15s)
        first_call = fake.direct_translate.await_args_list[0]
        assert first_call.kwargs["timeout"] == 15.0
        # 2回目呼び出し: Fallback (60s)
        second_call = fake.direct_translate.await_args_list[1]
        assert second_call.kwargs["timeout"] == 60.0


class TestHalfOpenRecovery:
    """HALF_OPEN 試行の決着に関する結合テスト（バグ1・バグ3の回帰）。

    HALF_OPEN 試行が RateLimitError で失敗した場合でも in-flight フラグが
    残留せず、OPEN 期間経過後に Primary を再試行できることを検証する。
    以前は record_success/record_failure を経由しないパスでフラグが残留し、
    allow() が永久に open を返して Primary が二度と試行されなくなっていた。
    """

    def test_HALF_OPEN試行がRateLimitErrorで失敗してもFallback成功後に再試行可能(self):
        import time as _time

        from py_modules.providers.base import RateLimitError

        pm, fake = _build_pm_with_fallback()
        # OPEN 期間切れの状態を作り、次の allow() で HALF_OPEN に遷移させる
        pm._circuit._open_until = _time.monotonic() - 1.0
        fake.direct_translate.side_effect = [
            RateLimitError("Gemini API returned status 429"),
            ([{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}], "pixel"),
        ]
        result = asyncio.get_event_loop().run_until_complete(
            pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
        )
        assert result is not None
        # Primary(RateLimitError) → Fallback(成功)
        assert fake.direct_translate.await_count == 2
        # in-flight フラグが残留せず決着済み
        assert pm._circuit._half_open_in_flight is False
        # 429 は混雑シグナルなので OPEN に戻るが、期間経過すれば Primary を再試行できる
        assert pm._circuit.get_state() == "open"
        pm._circuit._open_until = _time.monotonic() - 1.0
        assert pm._circuit.allow() == "half_open"

    def test_HALF_OPEN試行がApiKeyErrorで失敗しても固まらない(self):
        """ApiKeyError の即 raise パスでも finally 経由で必ず決着する。"""
        import time as _time

        from py_modules.providers.base import ApiKeyError

        pm, fake = _build_pm_with_fallback()
        pm._circuit._open_until = _time.monotonic() - 1.0
        fake.direct_translate.side_effect = ApiKeyError("invalid")
        with pytest.raises(ApiKeyError):
            asyncio.get_event_loop().run_until_complete(
                pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
            )
        # in-flight フラグが残留しない
        assert pm._circuit._half_open_in_flight is False
        # OPEN へ戻るので、期間経過後は再び HALF_OPEN 試行ができる
        pm._circuit._open_until = _time.monotonic() - 1.0
        assert pm._circuit.allow() == "half_open"

    def test_429もサーキットのrecord_failure対象(self):
        """バグ3: RateLimitError も混雑シグナルとしてカウントされる。"""
        from py_modules.providers.base import RateLimitError

        pm, fake = _build_pm_with_fallback()
        fake.direct_translate.return_value = (
            [{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}],
            "pixel",
        )

        # direct_translate を Primary(429)/Fallback(成功) で振り分ける
        results = []

        async def fake_translate(image_b64, source_lang, target_lang,
                                 w, h, **kwargs):
            if kwargs.get("timeout") == 15.0:
                raise RateLimitError("Gemini API returned status 429")
            return ([{"text": "hi", "translated_text": "やあ", "rect": {"left": 0, "top": 0, "right": 10, "bottom": 10}}], "pixel")

        fake.direct_translate = AsyncMock(side_effect=fake_translate)
        for _ in range(3):
            result = asyncio.get_event_loop().run_until_complete(
                pm.recognize_and_translate(b"img", "en", "ja", 100, 100)
            )
            results.append(result)

        # 全回 Fallback 成功で結果が返る
        assert all(r is not None for r in results)
        # 3回の 429 がカウントされ Circuit が OPEN になる
        assert pm._circuit.get_state() == "open"

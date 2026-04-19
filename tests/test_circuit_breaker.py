# tests/test_circuit_breaker.py
# CircuitBreaker の状態遷移テスト

from unittest.mock import patch

import pytest

from py_modules.providers.circuit_breaker import CircuitBreaker


@pytest.fixture
def cb():
    """小さめのパラメータでインスタンスを作成（テスト時間を節約）。"""
    return CircuitBreaker(threshold=3, window_sec=60.0, open_sec=60.0)


def _patch_now(cb, value):
    """CircuitBreaker._now() を指定値にモック。"""
    return patch.object(cb, "_now", return_value=value)


class TestClosedState:
    def test_初期状態はCLOSED(self, cb):
        assert cb.allow() == "closed"

    def test_閾値未満の失敗ではCLOSED維持(self, cb):
        with _patch_now(cb, 100.0):
            cb.record_failure()
            cb.record_failure()
            assert cb.allow() == "closed"

    def test_成功で失敗カウントがクリア(self, cb):
        with _patch_now(cb, 100.0):
            cb.record_failure()
            cb.record_failure()
            cb.record_success()
            cb.record_failure()
            cb.record_failure()
            assert cb.allow() == "closed"  # 成功で累積がリセットされた


class TestOpenTransition:
    def test_閾値到達でOPEN遷移(self, cb):
        with _patch_now(cb, 100.0):
            cb.record_failure()
            cb.record_failure()
            cb.record_failure()
            assert cb.allow() == "open"

    def test_OPEN中はPrimaryスキップ(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 130.0):  # 30秒後
            assert cb.allow() == "open"

    def test_ウィンドウ外の失敗は無視(self, cb):
        # 61秒前の失敗 → evict される
        with _patch_now(cb, 100.0):
            cb.record_failure()
            cb.record_failure()
        with _patch_now(cb, 170.0):  # 70秒後
            cb.record_failure()  # window外の2件はevictされ、この1件のみ残る
            assert cb.allow() == "closed"


class TestHalfOpen:
    def test_OPEN経過後はHALF_OPEN(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
            assert cb.allow() == "open"
        with _patch_now(cb, 165.0):  # 65秒後 → open_sec(60s)経過
            assert cb.allow() == "half_open"

    def test_HALF_OPENで成功したらCLOSED復帰(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            cb.allow()  # half_open に遷移
            cb.record_success()
            assert cb.allow() == "closed"

    def test_HALF_OPENで失敗したらOPENに戻る(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            cb.allow()  # half_open に遷移
            cb.record_failure()
            # OPEN 期間が新たに設定される
            assert cb.allow() == "open"
        with _patch_now(cb, 230.0):  # さらに 65秒後
            assert cb.allow() == "half_open"


class TestGetState:
    def test_副作用なしで状態取得(self, cb):
        assert cb.get_state() == "closed"
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
            assert cb.get_state() == "open"
        # get_state() は half_open への遷移をしないので、
        # OPEN 期間経過後でも CLOSED に見える（ただし allow() は half_open を返す）
        with _patch_now(cb, 165.0):
            # get_state の実装上、OPEN期間が切れたら closed と見える
            assert cb.get_state() == "closed"
            # allow() が呼ばれたら half_open に遷移
            assert cb.allow() == "half_open"

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


class TestSettle:
    """HALF_OPEN 試行の明示的決着（settle）のテスト。

    record_success()/record_failure() を経由しない失敗（ApiKeyError 等の
    即 raise、非 busy エラー）でも in-flight フラグが残留せず、
    allow() が永久に open を返す固まりが起きないことを検証する。
    """

    def test_HALF_OPEN中の非busy失敗でもsettleで決着する(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            assert cb.allow() == "half_open"
            # record_* を呼ばない非 busy 失敗を想定し、settle(False) のみで決着
            cb.settle(False)
            # in-flight フラグが残留せず OPEN へ復帰している
            assert cb._half_open_in_flight is False
            assert cb.allow() == "open"

    def test_settle後はOPEN期間経過で再試行できる(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            cb.allow()
            cb.settle(False)  # 非 busy 失敗 → OPEN へ戻る
        with _patch_now(cb, 230.0):  # open_sec(60s) 経過
            # 固まらず HALF_OPEN に遷移できる（バグ1の回帰）
            assert cb.allow() == "half_open"

    def test_record後のsettleは冪等(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            cb.allow()
            cb.record_failure()  # HALF_OPEN 失敗 → OPEN へ復帰済み
            # 二重に決着しても状態を壊さない
            cb.settle(False)
            assert cb.allow() == "open"

    def test_settle成功でCLOSED復帰(self, cb):
        with _patch_now(cb, 100.0):
            for _ in range(3):
                cb.record_failure()
        with _patch_now(cb, 165.0):
            cb.allow()
            cb.settle(True)
            assert cb.allow() == "closed"

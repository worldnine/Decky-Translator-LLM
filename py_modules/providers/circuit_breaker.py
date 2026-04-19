# providers/circuit_breaker.py
# Primary モデル用のサーキットブレーカー
#
# Gemini Preview モデル等のピーク帯で連続503が発生した場合、
# 一定時間 Primary をスキップして Fallback 直行させるための状態機械。
#
# 状態遷移:
#   CLOSED ──(window内失敗 ≥ threshold)──→ OPEN
#     ↑                                       │
#     │ HALF_OPEN で成功                     │ open_sec 経過
#     │                                       ↓
#     └──(成功)── CLOSED ←──┐              HALF_OPEN
#                           │                  │
#                           └── HALF_OPENで失敗 ─┘（OPENへ戻る）

import logging
import time
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Primary モデル失敗のしきい値監視とスキップ判定。

    スレッドセーフではない。ProviderManager が単一リクエストごとに
    allow()/record_* を順に呼ぶ前提。
    """

    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"

    def __init__(
        self,
        *,
        threshold: int = 3,
        window_sec: float = 300.0,
        open_sec: float = 300.0,
    ) -> None:
        self._threshold = threshold
        self._window = window_sec
        self._open_duration = open_sec
        self._failures: deque = deque()
        self._open_until: Optional[float] = None
        self._half_open_in_flight: bool = False

    def _now(self) -> float:
        return time.monotonic()

    def _evict_old_failures(self, now: float) -> None:
        while self._failures and (now - self._failures[0]) > self._window:
            self._failures.popleft()

    def allow(self) -> str:
        """現在の状態を返す。呼び出し側はこの値に応じて Primary を試行/スキップする。

        返値:
            "closed"    — Primary を試行（リトライあり）
            "half_open" — Primary を試行（1回だけ、リトライなし）
            "open"      — Primary をスキップ
        """
        now = self._now()
        self._evict_old_failures(now)

        if self._open_until is not None:
            if now >= self._open_until:
                # OPEN 期間終了 → HALF_OPEN へ遷移
                self._open_until = None
                self._half_open_in_flight = True
                logger.info("CircuitBreaker: OPEN → HALF_OPEN (primaryを1回だけ試行)")
                return self.STATE_HALF_OPEN
            return self.STATE_OPEN

        if self._half_open_in_flight:
            # 前回 HALF_OPEN で試行中にもう一度 allow() が呼ばれた
            # 同時並行リクエストは想定しないが、安全のため open として扱う
            return self.STATE_OPEN

        return self.STATE_CLOSED

    def record_failure(self) -> None:
        """Primary の server_busy 失敗を記録。しきい値超過で OPEN に遷移。"""
        now = self._now()

        if self._half_open_in_flight:
            # HALF_OPEN 試行が失敗 → OPEN に戻す
            self._half_open_in_flight = False
            self._open_until = now + self._open_duration
            logger.warning(
                f"CircuitBreaker: HALF_OPENで失敗 → OPENに復帰 "
                f"(次の試行まで {self._open_duration:.0f}秒)"
            )
            return

        self._failures.append(now)
        self._evict_old_failures(now)

        if len(self._failures) >= self._threshold:
            self._open_until = now + self._open_duration
            self._failures.clear()
            logger.warning(
                f"CircuitBreaker: 失敗{self._threshold}回でOPEN "
                f"(次の試行まで {self._open_duration:.0f}秒)"
            )

    def record_success(self) -> None:
        """成功を記録。HALF_OPEN なら CLOSED に復帰、CLOSED なら失敗カウントをクリア。"""
        if self._half_open_in_flight:
            self._half_open_in_flight = False
            self._failures.clear()
            self._open_until = None
            logger.info("CircuitBreaker: HALF_OPENで成功 → CLOSED復帰")
            return

        # CLOSED 時は単に失敗カウントを減らす（累積を防ぐ）
        if self._failures:
            self._failures.clear()

    def get_state(self) -> str:
        """状態問い合わせ専用（副作用なし）。ログやテスト用。"""
        now = self._now()
        if self._open_until is not None and now < self._open_until:
            return self.STATE_OPEN
        if self._half_open_in_flight:
            return self.STATE_HALF_OPEN
        return self.STATE_CLOSED

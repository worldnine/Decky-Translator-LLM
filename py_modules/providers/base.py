# providers/base.py
# エラー型定義 — Gemini Vision専用構成


class NetworkError(Exception):
    """ネットワーク接続エラー。"""
    pass


class ApiKeyError(Exception):
    """APIキーが無効または未設定。"""
    pass


class RateLimitError(Exception):
    """APIレートリミット超過。"""
    pass


class ConfigurationError(Exception):
    """設定が不足または不正な場合に送出する。ApiKeyErrorとは区別する。"""
    pass

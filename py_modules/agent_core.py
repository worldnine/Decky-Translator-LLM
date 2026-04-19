# agent_core.py
# Agent CLI / RPC 共通処理モジュール
# main.py の Plugin と CLI の両方から利用する

import asyncio
import base64
import json
import logging
import os
import signal
import struct
import time
import uuid
from asyncio.subprocess import PIPE
from datetime import datetime, timezone
from typing import Optional

from providers import ProviderManager, NetworkError, ApiKeyError

logger = logging.getLogger(__name__)

# スクリーンショット一時保存先
SCREENSHOT_DIR = "/tmp/decky-translator"

# GStreamer 関連パス（Decky実機環境）
DEFAULT_DECKY_HOME = "/home/deck"


def _get_deps_path(plugin_dir: str) -> str:
    """依存パッケージパスを返す。"""
    bin_path = os.path.join(plugin_dir, "bin")
    if os.path.exists(bin_path):
        return bin_path
    return os.path.join(plugin_dir, "backend/out")


def _get_base64_image(image_path: str) -> str:
    """画像ファイルをbase64エンコードする。"""
    try:
        if not os.path.exists(image_path):
            logger.error(f"画像ファイルが存在しません: {image_path}")
            return ""
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"画像のbase64エンコードに失敗: {e}")
        return ""


def _get_image_size_from_bytes(image_bytes: bytes) -> tuple:
    """PNGヘッダから画像サイズを取得する。"""
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        width = struct.unpack('>I', image_bytes[16:20])[0]
        height = struct.unpack('>I', image_bytes[20:24])[0]
        return width, height
    return None, None


def _now_iso() -> str:
    """現在時刻をISO 8601形式で返す。"""
    return datetime.now(timezone.utc).astimezone().isoformat()


NOTIFY_SOCKET_PATH = os.path.join(SCREENSHOT_DIR, "notify.sock")
GAME_INFO_FILE = os.path.join(SCREENSHOT_DIR, "running-game.json")


def write_running_game(app_id, display_name):
    """ゲーム情報をファイルに書き出す。null の場合はファイル削除。"""
    try:
        if app_id is None:
            if os.path.exists(GAME_INFO_FILE):
                os.remove(GAME_INFO_FILE)
            return
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        with open(GAME_INFO_FILE, "w") as f:
            json.dump({"app_id": app_id, "display_name": display_name}, f)
    except Exception as e:
        logger.debug(f"ゲーム情報ファイル書き込み失敗: {e}")


def read_running_game() -> dict:
    """ゲーム情報ファイルを読み取る。"""
    try:
        if not os.path.exists(GAME_INFO_FILE):
            return {"app_id": None, "display_name": None}
        with open(GAME_INFO_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"app_id": None, "display_name": None}


def notify_plugin(purpose: str = "", image_path: str = "", mode: str = "thumbnail"):
    """UDS経由でPluginプロセスに通知する (fire-and-forget)。

    mode:
        "dot"       — 🔴 のみ
        "thumbnail" — スクショサムネイルのみ
        "message"   — purpose テキストのみ
    """
    import socket as _socket
    try:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(NOTIFY_SOCKET_PATH)
        msg = json.dumps({
            "type": "agent_notification",
            "mode": mode,
            "purpose": purpose[:100] if purpose else "",
            "image_path": image_path,
        })
        sock.sendall((msg + "\n").encode("utf-8"))
        sock.close()
    except Exception:
        pass  # Pluginが起動していなくてもCLIは正常動作


def make_error_response(action: str, code: str, message: str, purpose: str = None) -> dict:
    """エラー応答の標準JSONを生成する。"""
    resp = {
        "ok": False,
        "action": action,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if purpose:
        resp["purpose"] = purpose
    return resp


def make_success_response(action: str, **kwargs) -> dict:
    """成功応答の標準JSONを生成する。"""
    resp = {"ok": True, "action": action}
    resp.update(kwargs)
    return resp


async def capture_screenshot(
    app_name: str = "",
    plugin_dir: str = None,
    decky_home: str = None,
) -> dict:
    """スクリーンショットを取得する。

    Returns:
        {"path": str, "base64": str, "captured_at": str} または
        {"error": str, "message": str}
    """
    decky_home = decky_home or DEFAULT_DECKY_HOME
    deps_path = _get_deps_path(plugin_dir) if plugin_dir else ""
    gst_plugins_path = os.path.join(deps_path, "gstreamer-1.0") if deps_path else ""

    # アプリ名のサニタイズ
    if not app_name or app_name.strip().lower() == "null":
        app_name = "Decky-Screenshot"
    else:
        app_name = app_name.replace(":", " ").replace("/", " ").strip()

    # ファイルパス構築（UUIDで一意化し、並行リクエスト時のファイル衝突を防ぐ）
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    unique_id = uuid.uuid4().hex[:8]
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    screenshot_path = f"{SCREENSHOT_DIR}/{app_name}_{timestamp}_{unique_id}.png"
    captured_at = _now_iso()

    # GStreamer 環境変数
    env = os.environ.copy()
    env.update({
        "XDG_RUNTIME_DIR": "/run/user/1000",
        "XDG_SESSION_TYPE": "wayland",
        "HOME": decky_home,
    })
    if gst_plugins_path:
        env["GST_PLUGIN_PATH"] = gst_plugins_path
    if deps_path:
        env["LD_LIBRARY_PATH"] = deps_path

    try:
        proc = await asyncio.create_subprocess_exec(
            "gst-launch-1.0", "-e",
            "pipewiresrc", "do-timestamp=true", "num-buffers=5",
            "!", "videoconvert",
            "!", "pngenc", "snapshot=true",
            "!", "filesink", f"location={screenshot_path}",
            stdout=PIPE, stderr=PIPE, env=env,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
        except asyncio.TimeoutError:
            logger.warning("GStreamer タイムアウト(5s)、SIGINTで停止")
            proc.send_signal(signal.SIGINT)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=2)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.communicate()

        if os.path.exists(screenshot_path) and os.path.getsize(screenshot_path) > 0:
            b64 = _get_base64_image(screenshot_path)
            if b64:
                return {
                    "path": screenshot_path,
                    "base64": b64,
                    "captured_at": captured_at,
                }
        return {"error": "capture_failed", "message": "スクリーンショットファイルが空またはなし"}

    except Exception as e:
        logger.error(f"スクリーンショット取得エラー: {e}")
        return {"error": "capture_failed", "message": str(e)}


async def translate_screen(
    provider_manager: ProviderManager,
    image_base64: str,
    target_lang: str = "ja",
    input_lang: str = "auto",
) -> dict:
    """スクリーンショットをVision翻訳する。

    Returns:
        {"regions": [...]} または {"error": str, "message": str}
    """
    try:
        # base64デコード
        img_str = image_base64
        if img_str.startswith("data:image"):
            img_str = img_str.split(",", 1)[1]
        image_bytes = base64.b64decode(img_str)

        width, height = _get_image_size_from_bytes(image_bytes)
        if not width or not height:
            return {"error": "translate_failed", "message": "画像サイズ取得に失敗"}

        start = time.time()
        result = await provider_manager.recognize_and_translate(
            image_bytes, input_lang, target_lang, width, height,
        )
        elapsed = time.time() - start

        if result is None:
            return {"error": "translate_failed", "message": "Vision翻訳が結果なし"}

        logger.info(f"Agent翻訳完了: {len(result)} regions ({elapsed:.2f}s)")
        return {"regions": result}

    except NetworkError as e:
        return {"error": "network_error", "message": str(e)}
    except ApiKeyError as e:
        return {"error": "api_key_error", "message": "APIキーが不正です"}
    except Exception as e:
        logger.error(f"Agent翻訳エラー: {e}")
        return {"error": "translate_failed", "message": str(e)}


async def describe_screen(
    provider_manager: ProviderManager,
    image_base64: str,
    prompt: str = None,
) -> dict:
    """スクリーンショットを攻略支援向けに説明する。

    Returns:
        {"description": {...}} または {"error": str, "message": str}
    """
    try:
        img_str = image_base64
        if img_str.startswith("data:image"):
            img_str = img_str.split(",", 1)[1]
        image_bytes = base64.b64decode(img_str)

        width, height = _get_image_size_from_bytes(image_bytes)
        if not width or not height:
            return {"error": "describe_failed", "message": "画像サイズ取得に失敗"}

        start = time.time()
        result = await provider_manager.describe_screen(
            image_bytes, width, height, prompt=prompt,
        )
        elapsed = time.time() - start

        if result is None:
            return {"error": "describe_failed", "message": "画面説明が結果なし"}

        logger.info(f"Agent画面説明完了 ({elapsed:.2f}s)")
        return {"description": result}

    except NetworkError as e:
        return {"error": "network_error", "message": str(e)}
    except ApiKeyError as e:
        return {"error": "api_key_error", "message": "APIキーが不正です"}
    except Exception as e:
        logger.error(f"Agent画面説明エラー: {e}")
        return {"error": "describe_failed", "message": str(e)}


def get_capabilities() -> dict:
    """利用可能な機能一覧を返す。"""
    return make_success_response(
        "capabilities",
        capabilities=["capture", "translate", "describe", "game", "prompt", "pin", "logs"],
        read_only=False,
    )

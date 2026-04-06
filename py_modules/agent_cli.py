#!/usr/bin/env python3
# agent_cli.py
# Decky Agent CLI — 外部AIおよび開発者向けのコマンドラインインターフェース
#
# 使用例:
#   decky-agent-cli capture --purpose "攻略支援: 画面確認" --json
#   decky-agent-cli translate --purpose "攻略支援: UI翻訳" --target ja --json
#   decky-agent-cli describe --purpose "攻略支援: 会話確認" --json
#   decky-agent-cli game --json
#   decky-agent-cli capabilities --json

import argparse
import asyncio
import json
import logging
import os
import sys

# パス設定: Decky Loaderランタイムと同等の構成にする
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.dirname(SCRIPT_DIR)  # py_modules の親 = プラグインルート

# py_modules を sys.path に追加
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# bin/py_modules（実機のpipパッケージ）
BIN_PY_MODULES = os.path.join(PLUGIN_DIR, "bin", "py_modules")
if os.path.exists(BIN_PY_MODULES) and BIN_PY_MODULES not in sys.path:
    sys.path.insert(0, BIN_PY_MODULES)

from agent_core import (
    capture_screenshot,
    translate_screen,
    describe_screen,
    get_capabilities,
    make_error_response,
    make_success_response,
    notify_plugin,
    read_running_game,
)
from providers import ProviderManager
from migration import normalize_gemini_setting, extract_prompt_from_content

logger = logging.getLogger("agent_cli")

# 終了コード
EXIT_OK = 0
EXIT_RUNTIME_ERROR = 1
EXIT_ARGS_ERROR = 2
EXIT_CONFIG_ERROR = 3

# 設定ファイルパス
DEFAULT_SETTINGS_DIR = os.environ.get(
    "DECKY_PLUGIN_SETTINGS_DIR",
    "/home/deck/homebrew/settings/decky-translator-llm",
)
DEFAULT_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _load_settings(settings_dir: str) -> dict:
    """Decky Translator の設定ファイルを読み込む。"""
    settings_path = os.path.join(settings_dir, "decky-translator-settings.json")
    if not os.path.exists(settings_path):
        return {}
    with open(settings_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _create_provider_manager(settings: dict) -> ProviderManager:
    """設定からProviderManagerを初期化する。"""
    def getter(key, default=None):
        return settings.get(key, default)

    base_url = normalize_gemini_setting(getter, "base_url", default="")
    api_key = normalize_gemini_setting(getter, "api_key", default="")
    model = normalize_gemini_setting(getter, "model", default="")
    disable_thinking = normalize_gemini_setting(getter, "disable_thinking", default=True)
    parallel = normalize_gemini_setting(getter, "parallel", default=True)
    coordinate_mode = settings.get(
        "vision_coordinate_mode",
        settings.get("llm_coordinate_mode", "pixel"),
    )

    if not base_url:
        base_url = DEFAULT_GEMINI_BASE_URL

    pm = ProviderManager()
    pm.configure_vision(
        mode="direct",
        base_url=base_url,
        api_key=api_key,
        model=model,
        disable_thinking=disable_thinking,
        parallel=parallel,
        coordinate_mode=coordinate_mode,
    )

    # 共通プロンプト読み込み
    prompts_dir = os.path.join(DEFAULT_SETTINGS_DIR, "decky-translator-prompts")
    vision_common_path = os.path.join(prompts_dir, "vision-common.txt")
    if os.path.exists(vision_common_path):
        with open(vision_common_path, "r", encoding="utf-8-sig") as f:
            pm.configure_vision(system_prompt=f.read().strip())

    return pm


def _check_agent_enabled(action: str):
    """設定ファイルの agent_enabled を確認する。
    未設定・欠落・false いずれもCLI無効として扱う（デフォルト無効、opt-in）。
    main.py 側の get_setting("agent_enabled", False) と同じ判定。"""
    settings = _load_settings(DEFAULT_SETTINGS_DIR)
    if not settings.get("agent_enabled", False):
        return make_error_response(action, "agent_disabled",
                                   "Agent CLI is disabled. Enable it in Decky Translator settings.")
    return None


def _get_prompts_dir() -> str:
    """共通プロンプトディレクトリを返す。"""
    return os.path.join(DEFAULT_SETTINGS_DIR, "decky-translator-prompts")


def _get_games_dir() -> str:
    """ゲーム別プロンプトディレクトリを返す。"""
    return os.path.join(DEFAULT_SETTINGS_DIR, "decky-translator-games")


def _output(data: dict, as_json: bool):
    """結果を出力する。"""
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
    else:
        _output_human(data)


def _output_human(data: dict):
    """人間向けの出力。"""
    ok = data.get("ok", False)
    action = data.get("action", "unknown")

    if not ok:
        err = data.get("error", {})
        print(f"エラー [{err.get('code', 'unknown')}]: {err.get('message', '不明')}", file=sys.stderr)
        return

    if action == "capture":
        print(f"スクリーンショット取得完了")
        print(f"  時刻: {data.get('captured_at', '?')}")
        game = data.get("game", {})
        if game.get("display_name"):
            print(f"  ゲーム: {game['display_name']}")
        img = data.get("image", {})
        if img.get("path"):
            print(f"  ファイル: {img['path']}")
        b64 = img.get("base64", "")
        if b64:
            print(f"  base64: {len(b64)} chars")

    elif action == "translate":
        regions = data.get("regions", [])
        print(f"翻訳完了: {len(regions)} テキスト領域")
        for i, r in enumerate(regions, 1):
            print(f"  [{i}] {r.get('text', '')} → {r.get('translatedText', '')}")

    elif action == "describe":
        desc = data.get("description", {})
        print(f"画面説明:")
        print(f"  要約: {desc.get('summary', '?')}")
        for obj in desc.get("objectives", []):
            print(f"  目的: {obj}")
        for ui in desc.get("ui", []):
            print(f"  UI: {ui}")
        for txt in desc.get("notable_text", []):
            print(f"  テキスト: {txt}")

    elif action == "game":
        game = data.get("game", {})
        if game.get("display_name"):
            print(f"ゲーム: {game['display_name']} (AppID: {game.get('app_id', '?')})")
        else:
            print("ゲームが起動していません")

    elif action == "capabilities":
        caps = data.get("capabilities", [])
        print(f"利用可能コマンド: {', '.join(caps)}")
        print(f"読み取り専用: {data.get('read_only', True)}")


async def cmd_capture(args):
    """capture サブコマンド"""
    err = _check_agent_enabled("capture")
    if err:
        return err
    result = await capture_screenshot(
        app_name=args.app_name or "",
        plugin_dir=PLUGIN_DIR,
    )

    if "error" in result:
        return make_error_response("capture", result["error"], result["message"], args.purpose)

    notify_plugin(args.purpose, result["path"], mode=getattr(args, "notify", "thumbnail"))

    return make_success_response(
        "capture",
        purpose=args.purpose,
        captured_at=result["captured_at"],
        game={"app_id": None, "display_name": args.app_name or None},
        image={
            "path": result["path"],
            "base64": f"data:image/png;base64,{result['base64']}",
        },
    )


def _cleanup_screenshot(cap_result: dict):
    """一時スクリーンショットファイルを削除する。"""
    path = cap_result.get("path")
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


async def cmd_translate(args):
    """translate サブコマンド"""
    err = _check_agent_enabled("translate")
    if err:
        return err
    settings = _load_settings(DEFAULT_SETTINGS_DIR)
    pm = _create_provider_manager(settings)

    # スクリーンショット取得
    cap_result = await capture_screenshot(
        app_name=args.app_name or "",
        plugin_dir=PLUGIN_DIR,
    )
    if "error" in cap_result:
        return make_error_response("translate", cap_result["error"], cap_result["message"], args.purpose)

    notify_plugin(args.purpose, cap_result.get("path", ""), mode=getattr(args, "notify", "thumbnail"))

    try:
        # 翻訳
        target = args.target or settings.get("target_language", "ja")
        input_lang = args.input or settings.get("input_language", "auto")

        tr_result = await translate_screen(pm, cap_result["base64"], target, input_lang)
        if "error" in tr_result:
            return make_error_response("translate", tr_result["error"], tr_result["message"], args.purpose)

        return make_success_response(
            "translate",
            purpose=args.purpose,
            captured_at=cap_result["captured_at"],
            game={"app_id": None, "display_name": args.app_name or None},
            regions=tr_result["regions"],
        )
    finally:
        _cleanup_screenshot(cap_result)


async def cmd_describe(args):
    """describe サブコマンド"""
    err = _check_agent_enabled("describe")
    if err:
        return err
    settings = _load_settings(DEFAULT_SETTINGS_DIR)
    pm = _create_provider_manager(settings)

    # スクリーンショット取得
    cap_result = await capture_screenshot(
        app_name=args.app_name or "",
        plugin_dir=PLUGIN_DIR,
    )
    if "error" in cap_result:
        return make_error_response("describe", cap_result["error"], cap_result["message"], args.purpose)

    notify_plugin(args.purpose, cap_result.get("path", ""), mode=getattr(args, "notify", "thumbnail"))

    try:
        # 画面説明
        desc_result = await describe_screen(pm, cap_result["base64"], prompt=args.prompt)
        if "error" in desc_result:
            return make_error_response("describe", desc_result["error"], desc_result["message"], args.purpose)

        return make_success_response(
            "describe",
            purpose=args.purpose,
            captured_at=cap_result["captured_at"],
            game={"app_id": None, "display_name": args.app_name or None},
            description=desc_result["description"],
        )
    finally:
        _cleanup_screenshot(cap_result)


async def cmd_game(args):
    """game サブコマンド — ゲーム情報を返す。"""
    err = _check_agent_enabled("game")
    if err:
        return err
    game = read_running_game()
    return make_success_response("game", game=game)


async def cmd_capabilities(args):
    """capabilities サブコマンド"""
    return get_capabilities()


async def cmd_prompt(args):
    """prompt サブコマンド — 共通/ゲーム別プロンプトの読み書き。"""
    err = _check_agent_enabled("prompt")
    if err:
        return err
    sub = args.prompt_action
    app_id = getattr(args, "app_id", None)
    as_json = getattr(args, "json", False)

    if sub == "get":
        if app_id:
            file_path = os.path.join(_get_games_dir(), str(app_id), "vision.txt")
        else:
            file_path = os.path.join(_get_prompts_dir(), "vision-common.txt")

        if not os.path.exists(file_path):
            if as_json:
                return make_success_response("prompt", content="", file_path=file_path, exists=False)
            print("", end="")
            return make_success_response("prompt")

        with open(file_path, "r", encoding="utf-8-sig") as f:
            content = f.read()

        if as_json:
            return make_success_response("prompt", content=content, file_path=file_path, exists=True)
        # テキストそのまま出力（パイプ向き）
        print(content, end="")
        return make_success_response("prompt")

    elif sub == "set":
        # 内容を取得
        if getattr(args, "stdin", False):
            content = sys.stdin.read()
        elif args.content is not None:
            content = args.content
        else:
            return make_error_response("prompt", "missing_content", "--content or --stdin is required")

        if app_id:
            game_dir = os.path.join(_get_games_dir(), str(app_id))
            os.makedirs(game_dir, exist_ok=True)
            file_path = os.path.join(game_dir, "vision.txt")
            # 既存ファイルの1行目（メタ行）を保持
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8-sig") as f:
                    first_line = f.readline()
                if first_line.startswith("---"):
                    content = first_line + content
        else:
            prompts_dir = _get_prompts_dir()
            os.makedirs(prompts_dir, exist_ok=True)
            file_path = os.path.join(prompts_dir, "vision-common.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        if as_json:
            return make_success_response("prompt", file_path=file_path, saved=True)
        print("Saved.")
        return make_success_response("prompt")

    return make_error_response("prompt", "invalid_action", "Use 'get' or 'set'")


def build_parser() -> argparse.ArgumentParser:
    """CLIパーサーを構築する。"""
    parser = argparse.ArgumentParser(
        prog="decky-agent-cli",
        description="Decky Translator Agent CLI — 外部AIおよび開発者向けインターフェース",
    )
    parser.add_argument("--json", action="store_true", help="JSON形式で出力")
    parser.add_argument("--debug", action="store_true", help="デバッグログを有効化")

    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # 共通オプション（各サブコマンドに追加するヘルパー）
    def _add_common(p):
        p.add_argument("--json", action="store_true", help="JSON形式で出力")
        p.add_argument("--debug", action="store_true", help="デバッグログを有効化")

    # 通知オプション（capture/translate/describe 共通）
    def _add_notify(p):
        p.add_argument("--notify", choices=["dot", "thumbnail", "message"], default="thumbnail",
                       help="通知モード: dot=🔴のみ, thumbnail=スクショ, message=テキスト (default: thumbnail)")

    # capture
    p_capture = subparsers.add_parser("capture", help="スクリーンショットを取得")
    p_capture.add_argument("--purpose", required=True, help="取得目的（通知に表示）")
    p_capture.add_argument("--app-name", help="アプリ名（ファイル名に使用）")
    _add_notify(p_capture)
    _add_common(p_capture)

    # translate
    p_translate = subparsers.add_parser("translate", help="画面を翻訳")
    p_translate.add_argument("--purpose", required=True, help="取得目的（通知に表示）")
    p_translate.add_argument("--target", help="翻訳先言語コード (例: ja)")
    p_translate.add_argument("--input", help="入力言語コード (例: auto)")
    p_translate.add_argument("--app-name", help="アプリ名")
    _add_notify(p_translate)
    _add_common(p_translate)

    # describe
    p_describe = subparsers.add_parser("describe", help="画面を説明（攻略支援）")
    p_describe.add_argument("--purpose", required=True, help="取得目的（通知に表示）")
    p_describe.add_argument("--prompt", help="追加の指示プロンプト")
    p_describe.add_argument("--app-name", help="アプリ名")
    _add_notify(p_describe)
    _add_common(p_describe)

    # game
    p_game = subparsers.add_parser("game", help="現在のゲーム情報を取得")
    _add_common(p_game)

    # capabilities
    p_caps = subparsers.add_parser("capabilities", help="利用可能な機能一覧")
    _add_common(p_caps)

    # prompt
    p_prompt = subparsers.add_parser("prompt", help="プロンプトの読み書き")
    p_prompt.add_argument("prompt_action", choices=["get", "set"], help="get=取得, set=設定")
    p_prompt.add_argument("--app-id", type=int, help="ゲームのApp ID（指定時はゲーム別プロンプト）")
    p_prompt.add_argument("--content", help="設定するプロンプト内容（set時）")
    p_prompt.add_argument("--stdin", action="store_true", help="stdinからプロンプトを読む（set時）")
    _add_common(p_prompt)

    return parser


COMMAND_MAP = {
    "capture": cmd_capture,
    "translate": cmd_translate,
    "describe": cmd_describe,
    "game": cmd_game,
    "capabilities": cmd_capabilities,
    "prompt": cmd_prompt,
}


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if not args.command:
        parser.print_help()
        sys.exit(EXIT_ARGS_ERROR)

    handler = COMMAND_MAP.get(args.command)
    if not handler:
        parser.print_help()
        sys.exit(EXIT_ARGS_ERROR)

    try:
        result = asyncio.run(handler(args))
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        result = make_error_response(
            args.command, "internal_error", str(e),
            getattr(args, "purpose", None),
        )

    as_json = getattr(args, "json", False)
    _output(result, as_json)

    if not result.get("ok", False):
        err_code = result.get("error", {}).get("code", "")
        if err_code in ("internal_error", "config_error"):
            sys.exit(EXIT_CONFIG_ERROR)
        sys.exit(EXIT_RUNTIME_ERROR)

    sys.exit(EXIT_OK)


if __name__ == "__main__":
    main()

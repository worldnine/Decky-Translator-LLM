# py_modules/migration.py
# 旧設定・旧ファイル構造からの移行ロジック
# main.py の Plugin クラスから切り出した純粋関数群

import os
import logging

logger = logging.getLogger("decky-translator")

# Gemini設定キーのフォールバック定義
# gemini_* > vision_llm_* > text_llm_* > llm_* の優先順位
GEMINI_SETTING_CANDIDATES = {
    "base_url": ["gemini_base_url", "vision_llm_base_url", "text_llm_base_url", "llm_base_url"],
    "api_key": ["gemini_api_key", "vision_llm_api_key", "text_llm_api_key", "llm_api_key"],
    "model": ["gemini_model", "vision_llm_model", "text_llm_model", "llm_model"],
    "disable_thinking": ["gemini_disable_thinking", "vision_llm_disable_thinking", "text_llm_disable_thinking", "llm_disable_thinking"],
    "parallel": ["gemini_parallel", "vision_llm_parallel", "text_llm_parallel", "llm_parallel"],
}


def normalize_gemini_setting(settings_getter, key: str, default=""):
    """旧設定キーから gemini_* へのフォールバック正規化。

    settings_getter: settings.get_setting(key, default) 相当の callable、
                     または dict（テスト用）
    key: "base_url", "api_key", "model" 等
    default: 全候補が空の場合の既定値
    """
    candidates = GEMINI_SETTING_CANDIDATES[key]

    _sentinel = object()

    if isinstance(settings_getter, dict):
        # テスト用: dict を直接渡す
        for candidate in candidates:
            value = settings_getter.get(candidate, _sentinel)
            if value is not _sentinel:
                return value
        return default

    # 本番用: ネストした get_setting フォールバック
    result = default
    for candidate in reversed(candidates):
        result = settings_getter(candidate, result)
    return result


def extract_prompt_from_content(content: str) -> str:
    """ファイル内容から1行目のメタ行を除去し、プロンプト部分のみ返す。
    1行目が '--- ... ---' パターンの場合のみ除去。それ以外は全てプロンプト。"""
    lines = content.split("\n")
    if lines and lines[0].startswith("---") and lines[0].endswith("---"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def migrate_llm_system_prompt(prompts_dir: str, old_system_prompt: str) -> bool:
    """旧 llm_system_prompt → vision-common.txt 移行。

    vision-common.txt が存在しない場合のみ旧設定を書き込む。
    返り値: 移行が行われた場合 True
    """
    vision_common_path = os.path.join(prompts_dir, "vision-common.txt")
    if not os.path.exists(vision_common_path) and old_system_prompt:
        os.makedirs(prompts_dir, exist_ok=True)
        with open(vision_common_path, 'w', encoding='utf-8') as f:
            f.write(old_system_prompt)
        logger.info("旧 llm_system_prompt を vision-common.txt に移行")
        return True
    return False


def ensure_vision_common_file(prompts_dir: str) -> str:
    """vision-common.txt の確保。旧 text-common.txt からの移行を含む。

    - vision-common.txt が無く text-common.txt がある → rename
    - vision-common.txt が無く text-common.txt も無い → 空ファイル生成
    - vision-common.txt がある → そのまま

    返り値: ファイルの内容（strip済み）
    """
    vision_common_path = os.path.join(prompts_dir, "vision-common.txt")
    legacy_text_common_path = os.path.join(prompts_dir, "text-common.txt")

    if not os.path.exists(vision_common_path):
        os.makedirs(prompts_dir, exist_ok=True)
        if os.path.exists(legacy_text_common_path):
            os.rename(legacy_text_common_path, vision_common_path)
            logger.info("text-common.txt を vision-common.txt に移行")
        else:
            with open(vision_common_path, 'w', encoding='utf-8') as f:
                f.write("")
            logger.info("vision-common.txt を生成（空）")

    with open(vision_common_path, 'r', encoding='utf-8-sig') as f:
        return f.read().strip()


def migrate_old_game_prompt(games_dir: str, app_id: int) -> None:
    """旧形式のゲーム別 prompt を {app_id}/vision.txt へ移行する。

    移行候補（優先順）:
    1. {app_id}/text.txt → {app_id}/vision.txt
    2. {app_id}.txt → {app_id}/vision.txt
    """
    new_dir = os.path.join(games_dir, str(app_id))
    new_path = os.path.join(new_dir, "vision.txt")

    if os.path.exists(new_path):
        return

    legacy_candidates = [
        os.path.join(new_dir, "text.txt"),
        os.path.join(games_dir, f"{app_id}.txt"),
    ]

    for old_path in legacy_candidates:
        if not os.path.exists(old_path):
            continue
        os.makedirs(new_dir, exist_ok=True)
        os.rename(old_path, new_path)
        logger.info(f"ゲーム別プロンプト移行: {old_path} → {new_path}")
        break

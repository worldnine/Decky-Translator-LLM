# translation_history.py
# 翻訳履歴のJSONLログ記録・検索モジュール

import fcntl
import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("decky-translator")

HISTORY_DIR_NAME = "history"
JSONL_FILENAME = "translations.jsonl"
MAX_FILE_BYTES = 10 * 1024 * 1024  # 10MB


def _history_path(log_dir: str, app_id: str) -> Path:
    """ゲーム別のJSONLファイルパスを返す。"""
    return Path(log_dir) / HISTORY_DIR_NAME / str(app_id) / JSONL_FILENAME


def _normalize_regions(regions: list) -> list:
    """regionリストから text と translated_text のみ抽出。
    translatedText (camelCase) → translated_text に正規化。"""
    normalized = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        text = r.get("text", "")
        translated = r.get("translated_text") or r.get("translatedText") or ""
        if text or translated:
            normalized.append({"text": str(text), "translated_text": str(translated)})
    return normalized


def _rotate_if_needed(filepath: Path, lock_fd, max_bytes: int = MAX_FILE_BYTES):
    """ファイルサイズが上限を超えた場合、新しい方の半分を残す。
    呼び出し元でロック取得済みであること。"""
    try:
        size = filepath.stat().st_size
        if size <= max_bytes:
            return
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 新しい方（後半）を残す
        keep = lines[len(lines) // 2:]
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(keep)
        logger.info(f"翻訳履歴ローテーション: {len(lines)} → {len(keep)} 行 ({filepath})")
    except Exception as e:
        logger.debug(f"翻訳履歴ローテーション失敗: {e}")


def log_translation(
    log_dir: str,
    app_id: str,
    app_name: str,
    source: str,
    target_lang: str,
    input_lang: str,
    regions: list,
):
    """翻訳結果をJSONLファイルに1行追記する。"""
    if not regions:
        return

    filepath = _history_path(log_dir, app_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "app_id": str(app_id),
        "app_name": app_name,
        "source": source,
        "target_lang": target_lang,
        "input_lang": input_lang,
        "regions": _normalize_regions(regions),
    }

    lock_path = filepath.with_suffix(".lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            _rotate_if_needed(filepath, lock_fd)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def search_history(log_dir: str, app_id: str, keyword: str, limit: int = 50) -> list:
    """キーワードで翻訳履歴を検索する。新しい順で返す。"""
    filepath = _history_path(log_dir, app_id)
    if not filepath.exists():
        return []

    keyword_lower = keyword.lower()
    matches = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 新しい順（末尾から）で検索
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        for region in entry.get("regions", []):
            text = region.get("text", "").lower()
            translated = region.get("translated_text", "").lower()
            if keyword_lower in text or keyword_lower in translated:
                matches.append(entry)
                break

        if len(matches) >= limit:
            break

    return matches


def list_recent(log_dir: str, app_id: str, limit: int = 20) -> list:
    """直近N件の翻訳履歴を返す。新しい順。"""
    filepath = _history_path(log_dir, app_id)
    if not filepath.exists():
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    entries = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(entries) >= limit:
            break

    return entries


def list_games(log_dir: str) -> list:
    """履歴のあるゲーム一覧を返す。各ゲームのエントリ数付き。"""
    history_dir = Path(log_dir) / HISTORY_DIR_NAME
    if not history_dir.exists():
        return []

    games = []
    for entry in sorted(history_dir.iterdir()):
        if not entry.is_dir():
            continue
        jsonl = entry / JSONL_FILENAME
        if not jsonl.exists():
            continue

        # 行数カウント
        count = 0
        try:
            with open(jsonl, "r", encoding="utf-8") as f:
                for _ in f:
                    count += 1
        except Exception:
            pass

        # 最新エントリからapp_nameを取得
        app_name = ""
        try:
            with open(jsonl, "r", encoding="utf-8") as f:
                last_line = ""
                for last_line in f:
                    pass
                if last_line.strip():
                    app_name = json.loads(last_line.strip()).get("app_name", "")
        except Exception:
            pass

        games.append({
            "app_id": entry.name,
            "app_name": app_name,
            "count": count,
        })

    return games


# --- ゲーム別オンオフ設定 ---

GAMES_DIR_NAME = "decky-translator-games"
HISTORY_CONFIG_FILENAME = "history.json"


def _history_config_path(settings_dir: str, app_id: str) -> Path:
    """ゲーム別の履歴設定ファイルパスを返す。"""
    return Path(settings_dir) / GAMES_DIR_NAME / str(app_id) / HISTORY_CONFIG_FILENAME


def is_history_enabled(settings_dir: str, app_id: str) -> bool:
    """ゲームの翻訳履歴記録が有効かどうかを返す。
    設定ファイルが存在しない場合はデフォルトON。"""
    config_path = _history_config_path(settings_dir, app_id)
    try:
        if not config_path.exists():
            return True
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("enabled", True))
    except Exception:
        return True


def set_history_enabled(settings_dir: str, app_id: str, enabled: bool):
    """ゲームの翻訳履歴記録のオンオフを設定する。"""
    config_path = _history_config_path(settings_dir, app_id)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump({"enabled": enabled}, f)
    logger.info(f"翻訳履歴設定変更: app_id={app_id}, enabled={enabled}")


def get_game_history_info(log_dir: str, settings_dir: str, app_id: str) -> dict:
    """ゲームの翻訳履歴の情報を返す（削除前の確認用）。"""
    filepath = _history_path(log_dir, app_id)
    enabled = is_history_enabled(settings_dir, app_id)

    if not filepath.exists():
        return {"app_id": app_id, "enabled": enabled, "count": 0, "size_bytes": 0}

    count = 0
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for _ in f:
                count += 1
    except Exception:
        pass

    size_bytes = 0
    try:
        size_bytes = filepath.stat().st_size
    except Exception:
        pass

    return {
        "app_id": app_id,
        "enabled": enabled,
        "count": count,
        "size_bytes": size_bytes,
    }


def delete_game_history(log_dir: str, app_id: str) -> dict:
    """ゲームの翻訳履歴をディレクトリごと削除する。"""
    history_dir = Path(log_dir) / HISTORY_DIR_NAME / str(app_id)
    if not history_dir.exists():
        return {"deleted": False, "reason": "履歴が存在しません", "count": 0}

    # 削除前に件数を取得
    jsonl = history_dir / JSONL_FILENAME
    count = 0
    if jsonl.exists():
        try:
            with open(jsonl, "r", encoding="utf-8") as f:
                for _ in f:
                    count += 1
        except Exception:
            pass

    shutil.rmtree(history_dir)
    logger.info(f"翻訳履歴削除: app_id={app_id}, {count} 件")
    return {"deleted": True, "count": count}

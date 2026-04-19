# pin_history.py
# ピン履歴のJSONLログ記録・検索モジュール
# 画像つきの永続レコードとして管理する。translation_history.py とは別ストア。

import fcntl
import json
import logging
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("decky-translator")

PINS_DIR_NAME = "pins"
JSONL_FILENAME = "pins.jsonl"
IMAGES_DIR_NAME = "images"
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20MB（画像パス含むためやや大きめ）


def _pins_dir(log_dir: str, app_id: str) -> Path:
    """ゲーム別のピンディレクトリを返す。"""
    return Path(log_dir) / PINS_DIR_NAME / str(app_id)


def _jsonl_path(log_dir: str, app_id: str) -> Path:
    """ゲーム別のJSONLファイルパスを返す。"""
    return _pins_dir(log_dir, app_id) / JSONL_FILENAME


def _images_dir(log_dir: str, app_id: str) -> Path:
    """ゲーム別の画像保存ディレクトリを返す。"""
    return _pins_dir(log_dir, app_id) / IMAGES_DIR_NAME


def generate_pin_id() -> str:
    """ピンIDを生成する。タイムスタンプ + 短いランダムサフィックス。"""
    ts = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
    suffix = uuid.uuid4().hex[:8]
    return f"{ts}_{suffix}"


def _rotate_if_needed(filepath: Path, max_bytes: int = MAX_FILE_BYTES):
    """ファイルサイズが上限を超えた場合、新しい方の半分を残す。"""
    try:
        size = filepath.stat().st_size
        if size <= max_bytes:
            return
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
        keep = lines[len(lines) // 2:]
        with open(filepath, "w", encoding="utf-8") as f:
            f.writelines(keep)
        logger.info(f"ピン履歴ローテーション: {len(lines)} → {len(keep)} 行 ({filepath})")
    except Exception as e:
        logger.debug(f"ピン履歴ローテーション失敗: {e}")


def save_image(log_dir: str, app_id: str, pin_id: str, image_bytes: bytes) -> str:
    """画像を永続保存し、保存パスを返す。"""
    images = _images_dir(log_dir, app_id)
    images.mkdir(parents=True, exist_ok=True)

    # ファイル名: pin_idからタイムスタンプ部分を使う
    ts_part = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = pin_id.split("_")[-1] if "_" in pin_id else pin_id[:8]
    filename = f"{ts_part}_{suffix}.png"
    filepath = images / filename

    with open(filepath, "wb") as f:
        f.write(image_bytes)

    logger.info(f"ピン画像保存: {filepath} ({len(image_bytes)} bytes)")
    return str(filepath)


def build_search_text(regions: list) -> str:
    """検索用テキストを生成する。"""
    parts = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        text = r.get("text", "")
        translated = r.get("translated_text") or r.get("translatedText") or ""
        if text:
            parts.append(text)
        if translated:
            parts.append(translated)
    return "\n".join(parts)


def normalize_regions(regions: list) -> list:
    """regionリストを正規化する。座標情報も保持。"""
    normalized = []
    for r in regions:
        if not isinstance(r, dict):
            continue
        entry = {}
        text = r.get("text", "")
        translated = r.get("translated_text") or r.get("translatedText") or ""
        if text:
            entry["text"] = str(text)
        if translated:
            entry["translated_text"] = str(translated)
        rect = r.get("rect")
        if rect and isinstance(rect, dict):
            entry["rect"] = {
                "left": rect.get("left", 0),
                "top": rect.get("top", 0),
                "right": rect.get("right", 0),
                "bottom": rect.get("bottom", 0),
            }
        if entry:
            normalized.append(entry)
    return normalized


def create_pin_record(
    pin_id: str,
    app_id: int,
    game_name: str,
    trigger: str,
    capture_source: str,
    image_path: str,
    analysis_status: str = "pending",
    analysis_model: str = "",
    input_language: str = "",
    target_language: str = "",
    regions: list = None,
    error: str = None,
) -> dict:
    """ピンレコードを生成する。"""
    regions = regions or []
    normalized = normalize_regions(regions)

    recognized_parts = []
    translated_parts = []
    for r in normalized:
        if r.get("text"):
            recognized_parts.append(r["text"])
        if r.get("translated_text"):
            translated_parts.append(r["translated_text"])

    return {
        "schema_version": 1,
        "pin_id": pin_id,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f"),
        "app_id": int(app_id),
        "game_name": game_name,
        "trigger": trigger,
        "capture_source": capture_source,
        "image_path": image_path,
        "analysis_status": analysis_status,
        "analysis_model": analysis_model,
        "input_language": input_language,
        "target_language": target_language,
        "regions": normalized,
        "recognized_text": "\n".join(recognized_parts),
        "translated_text": "\n".join(translated_parts),
        "search_text": build_search_text(normalized),
        "error": error,
    }


def append_record(log_dir: str, app_id: str, record: dict):
    """ピンレコードをJSONLファイルに追記する。"""
    filepath = _jsonl_path(log_dir, app_id)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    lock_path = filepath.with_suffix(".lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            _rotate_if_needed(filepath)
            with open(filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def update_record(log_dir: str, app_id: str, pin_id: str, updates: dict):
    """既存レコードを更新する（同一pin_idの最新エントリを書き換え）。"""
    filepath = _jsonl_path(log_dir, app_id)
    if not filepath.exists():
        return

    lock_path = filepath.with_suffix(".lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # 末尾から探して最初に見つかった同一pin_idを更新
            updated = False
            for i in range(len(lines) - 1, -1, -1):
                line = lines[i].strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("pin_id") == pin_id:
                    entry.update(updates)
                    lines[i] = json.dumps(entry, ensure_ascii=False) + "\n"
                    updated = True
                    break

            if updated:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.writelines(lines)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def list_recent(log_dir: str, app_id: str, limit: int = 20) -> list:
    """直近N件のピン履歴を返す。新しい順。"""
    filepath = _jsonl_path(log_dir, app_id)
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


def search_history(log_dir: str, app_id: str, keyword: str, limit: int = 50) -> list:
    """キーワードでピン履歴を検索する。新しい順で返す。"""
    filepath = _jsonl_path(log_dir, app_id)
    if not filepath.exists():
        return []

    keyword_lower = keyword.lower()
    matches = []

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        search_text = entry.get("search_text", "").lower()
        if keyword_lower in search_text:
            matches.append(entry)

        if len(matches) >= limit:
            break

    return matches


def get_history_info(log_dir: str, app_id: str) -> dict:
    """ピン履歴の件数・サイズ情報を返す。"""
    filepath = _jsonl_path(log_dir, app_id)
    images = _images_dir(log_dir, app_id)

    count = 0
    jsonl_size = 0
    images_size = 0

    if filepath.exists():
        try:
            jsonl_size = filepath.stat().st_size
            with open(filepath, "r", encoding="utf-8") as f:
                for _ in f:
                    count += 1
        except Exception:
            pass

    if images.exists():
        try:
            for img in images.iterdir():
                if img.is_file():
                    images_size += img.stat().st_size
        except Exception:
            pass

    return {
        "app_id": str(app_id),
        "count": count,
        "jsonl_size_bytes": jsonl_size,
        "images_size_bytes": images_size,
        "total_size_bytes": jsonl_size + images_size,
    }


def get_pin_by_id(log_dir: str, app_id: str, pin_id: str) -> dict:
    """pin_id で 1 件取得する。見つからなければ空 dict。"""
    filepath = _jsonl_path(log_dir, app_id)
    if not filepath.exists():
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("pin_id") == pin_id:
            return entry
    return {}


def complete_analysis(log_dir: str, app_id: str, pin_id: str,
                      regions: list, model: str = "", error: str = None):
    """解析結果をレコードに反映するサービス関数。"""
    if error:
        update_record(log_dir, app_id, pin_id, {
            "analysis_status": "failed",
            "error": error,
        })
        return

    normalized = normalize_regions(regions)
    recognized = [r.get("text", "") for r in normalized if r.get("text")]
    translated = [r.get("translated_text", "") for r in normalized if r.get("translated_text")]

    update_record(log_dir, app_id, pin_id, {
        "analysis_status": "complete",
        "analysis_model": model,
        "regions": normalized,
        "recognized_text": "\n".join(recognized),
        "translated_text": "\n".join(translated),
        "search_text": build_search_text(normalized),
        "error": None,
    })


def delete_game_pins(log_dir: str, app_id: str) -> dict:
    """ゲームのピン履歴をディレクトリごと削除する。"""
    pins_dir = _pins_dir(log_dir, app_id)
    if not pins_dir.exists():
        return {"deleted": False, "reason": "ピン履歴が存在しません", "count": 0}

    # 削除前に件数を取得
    filepath = _jsonl_path(log_dir, app_id)
    count = 0
    if filepath.exists():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for _ in f:
                    count += 1
        except Exception:
            pass

    shutil.rmtree(pins_dir)
    logger.info(f"ピン履歴削除: app_id={app_id}, {count} 件")
    return {"deleted": True, "count": count}

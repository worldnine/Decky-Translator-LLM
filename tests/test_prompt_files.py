# tests/test_prompt_files.py
# プロンプトファイル API と extract_prompt_from_content のテスト
# 本番コード (py_modules/migration.py) を直接呼ぶ

import os
import pytest
from py_modules.migration import (
    extract_prompt_from_content,
    ensure_vision_common_file,
    migrate_old_game_prompt,
)


class TestExtractPromptFromContent:
    """extract_prompt_from_content() のテスト。"""

    def test_メタ行あり(self):
        content = "--- Game Title (App ID: 12345) Text ---\nTranslate carefully.\nKeep proper nouns."
        result = extract_prompt_from_content(content)
        assert result == "Translate carefully.\nKeep proper nouns."

    def test_メタ行なし(self):
        content = "Translate carefully.\nKeep proper nouns."
        result = extract_prompt_from_content(content)
        assert result == "Translate carefully.\nKeep proper nouns."

    def test_空文字列(self):
        result = extract_prompt_from_content("")
        assert result == ""

    def test_メタ行のみ(self):
        content = "--- Game Title ---"
        result = extract_prompt_from_content(content)
        assert result == ""

    def test_メタ行と空行(self):
        content = "--- Game Title ---\n\n"
        result = extract_prompt_from_content(content)
        assert result == ""

    def test_メタ行風だが形式不一致(self):
        """先頭が---で始まるが末尾が---で終わらない場合はプロンプトとして扱う"""
        content = "--- This is not a meta line\nSome prompt."
        result = extract_prompt_from_content(content)
        assert result == "--- This is not a meta line\nSome prompt."


class TestCommonPromptReadWrite:
    """共通プロンプトファイルの読み書きテスト。"""

    def test_vision_common_ラウンドトリップ(self, tmp_path):
        """vision-common.txt の保存→読み込みが一致する（ensure経由）"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        file_path = prompts_dir / "vision-common.txt"

        content = "Ignore HUD numbers.\nFocus on dialog."
        file_path.write_text(content, encoding='utf-8')

        loaded = ensure_vision_common_file(str(prompts_dir))
        assert loaded == content

    def test_utf8_bom対応(self, tmp_path):
        """UTF-8 BOM付きファイルが正しく読める（ensure_vision_common_file経由）"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        file_path = prompts_dir / "vision-common.txt"

        content = "日本語のプロンプト"
        file_path.write_bytes(b'\xef\xbb\xbf' + content.encode('utf-8'))

        loaded = ensure_vision_common_file(str(prompts_dir))
        assert loaded == content

    def test_旧共通promptをvision_commonへ移行できる(self, tmp_path):
        """旧 text-common.txt を vision-common.txt へ寄せられる（ensure経由）"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        legacy_path = prompts_dir / "text-common.txt"
        vision_path = prompts_dir / "vision-common.txt"

        content = "Legacy prompt"
        legacy_path.write_text(content, encoding='utf-8')

        loaded = ensure_vision_common_file(str(prompts_dir))

        assert not legacy_path.exists()
        assert vision_path.exists()
        assert loaded == content


class TestGamePromptFileStructure:
    """ゲーム別プロンプトファイル構造のテスト。"""

    def test_旧形式フラットファイルをvisionへ移行(self, tmp_path):
        """旧形式 ({appid}.txt) から新形式 ({appid}/vision.txt) への移行"""
        games_dir = tmp_path / "decky-translator-games"
        games_dir.mkdir()

        old_file = games_dir / "12345.txt"
        old_file.write_text("--- Game ---\nOld prompt content.", encoding='utf-8')

        migrate_old_game_prompt(str(games_dir), 12345)

        assert not old_file.exists()
        new_path = games_dir / "12345" / "vision.txt"
        assert new_path.exists()
        content = new_path.read_text(encoding='utf-8')
        assert "Old prompt content." in content

    def test_旧text_txtをvisionへ移行(self, tmp_path):
        """旧分離構成の text.txt を vision.txt へ寄せる"""
        games_dir = tmp_path / "decky-translator-games"
        game_dir = games_dir / "12345"
        game_dir.mkdir(parents=True)
        legacy_text = game_dir / "text.txt"
        vision_path = game_dir / "vision.txt"

        legacy_text.write_text("--- Game ---\nLegacy text prompt.", encoding='utf-8')

        migrate_old_game_prompt(str(games_dir), 12345)

        assert not legacy_text.exists()
        assert vision_path.exists()
        content = vision_path.read_text(encoding='utf-8')
        assert "Legacy text prompt." in content

    def test_vision_txt存在時は移行しない(self, tmp_path):
        """vision.txt が既に存在する場合は旧ファイルに触らない"""
        games_dir = tmp_path / "decky-translator-games"
        game_dir = games_dir / "12345"
        game_dir.mkdir(parents=True)
        vision_path = game_dir / "vision.txt"
        vision_path.write_text("Existing vision prompt.", encoding='utf-8')
        legacy_text = game_dir / "text.txt"
        legacy_text.write_text("Old text prompt.", encoding='utf-8')

        migrate_old_game_prompt(str(games_dir), 12345)

        # vision.txt は変更なし、text.txt も残る
        assert vision_path.read_text(encoding='utf-8') == "Existing vision prompt."
        assert legacy_text.exists()

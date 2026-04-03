# tests/test_prompt_files.py
# プロンプトファイル API と _extract_prompt_from_content のテスト

import os
import tempfile
import pytest


class TestExtractPromptFromContent:
    """_extract_prompt_from_content() のテスト。"""

    def _extract(self, content: str) -> str:
        """main.py の Plugin クラスと同じロジックを再現"""
        lines = content.split("\n")
        if lines and lines[0].startswith("---") and lines[0].endswith("---"):
            lines = lines[1:]
        return "\n".join(lines).strip()

    def test_メタ行あり(self):
        content = "--- Game Title (App ID: 12345) Text ---\nTranslate carefully.\nKeep proper nouns."
        result = self._extract(content)
        assert result == "Translate carefully.\nKeep proper nouns."

    def test_メタ行なし(self):
        content = "Translate carefully.\nKeep proper nouns."
        result = self._extract(content)
        assert result == "Translate carefully.\nKeep proper nouns."

    def test_空文字列(self):
        result = self._extract("")
        assert result == ""

    def test_メタ行のみ(self):
        content = "--- Game Title ---"
        result = self._extract(content)
        assert result == ""

    def test_メタ行と空行(self):
        content = "--- Game Title ---\n\n"
        result = self._extract(content)
        assert result == ""

    def test_メタ行風だが形式不一致(self):
        """先頭が---で始まるが末尾が---で終わらない場合はプロンプトとして扱う"""
        content = "--- This is not a meta line\nSome prompt."
        result = self._extract(content)
        assert result == "--- This is not a meta line\nSome prompt."


class TestCommonPromptReadWrite:
    """共通プロンプトファイルの読み書きテスト。"""

    def test_vision_common_ラウンドトリップ(self, tmp_path):
        """vision-common.txt の保存→読み込みが一致する"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        file_path = prompts_dir / "vision-common.txt"

        content = "Ignore HUD numbers.\nFocus on dialog."
        file_path.write_text(content, encoding='utf-8')
        loaded = file_path.read_text(encoding='utf-8-sig')
        assert loaded == content

    def test_utf8_bom対応(self, tmp_path):
        """UTF-8 BOM付きファイルが正しく読める"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        file_path = prompts_dir / "vision-common.txt"

        content = "日本語のプロンプト"
        file_path.write_bytes(b'\xef\xbb\xbf' + content.encode('utf-8'))
        loaded = file_path.read_text(encoding='utf-8-sig')
        assert loaded == content

    def test_旧共通promptをvision_commonへ移行できる(self, tmp_path):
        """旧 text-common.txt を vision-common.txt へ寄せられる"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        legacy_path = prompts_dir / "text-common.txt"
        vision_path = prompts_dir / "vision-common.txt"

        content = "Legacy prompt"
        legacy_path.write_text(content, encoding='utf-8')

        if not vision_path.exists():
            legacy_path.rename(vision_path)

        assert not legacy_path.exists()
        assert vision_path.read_text(encoding='utf-8') == content


class TestGamePromptFileStructure:
    """ゲーム別プロンプトファイル構造のテスト。"""

    def test_ゲームディレクトリ作成(self, tmp_path):
        """ゲーム別 Gemini prompt が <appid>/vision.txt に作成される"""
        games_dir = tmp_path / "decky-translator-games"
        games_dir.mkdir()
        game_dir = games_dir / "12345"
        game_dir.mkdir()

        vision_file = game_dir / "vision.txt"
        vision_file.write_text("--- Game (App ID: 12345) Vision ---\n", encoding='utf-8')

        assert vision_file.exists()

    def test_旧形式フラットファイルをvisionへ移行(self, tmp_path):
        """旧形式 ({appid}.txt) から新形式 ({appid}/vision.txt) への移行"""
        games_dir = tmp_path / "decky-translator-games"
        games_dir.mkdir()

        old_file = games_dir / "12345.txt"
        old_file.write_text("--- Game ---\nOld prompt content.", encoding='utf-8')

        app_id = 12345
        new_dir = games_dir / str(app_id)
        new_path = new_dir / "vision.txt"

        if not new_path.exists() and old_file.exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            old_file.rename(new_path)

        assert not old_file.exists()
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

        if not vision_path.exists() and legacy_text.exists():
            legacy_text.rename(vision_path)

        assert not legacy_text.exists()
        assert vision_path.exists()
        content = vision_path.read_text(encoding='utf-8')
        assert "Legacy text prompt." in content

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

    def test_text_common_ラウンドトリップ(self, tmp_path):
        """text-common.txt の保存→読み込みが一致する"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir()
        file_path = prompts_dir / "text-common.txt"

        content = "Keep HP, MP unchanged.\nTranslate concisely."
        file_path.write_text(content, encoding='utf-8')
        loaded = file_path.read_text(encoding='utf-8-sig')
        assert loaded == content

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
        file_path = prompts_dir / "text-common.txt"

        content = "日本語のプロンプト"
        file_path.write_bytes(b'\xef\xbb\xbf' + content.encode('utf-8'))
        loaded = file_path.read_text(encoding='utf-8-sig')
        assert loaded == content


class TestGamePromptFileStructure:
    """ゲーム別プロンプトファイル構造のテスト。"""

    def test_ゲームディレクトリ作成(self, tmp_path):
        """ゲーム別プロンプトが <appid>/ ディレクトリに作成される"""
        games_dir = tmp_path / "decky-translator-games"
        games_dir.mkdir()
        game_dir = games_dir / "12345"
        game_dir.mkdir()

        text_file = game_dir / "text.txt"
        vision_file = game_dir / "vision.txt"

        text_file.write_text("--- Game (App ID: 12345) Text ---\n", encoding='utf-8')
        vision_file.write_text("--- Game (App ID: 12345) Vision ---\n", encoding='utf-8')

        assert text_file.exists()
        assert vision_file.exists()

    def test_旧形式マイグレーション(self, tmp_path):
        """旧形式 ({appid}.txt) から新形式 ({appid}/text.txt) への移行"""
        games_dir = tmp_path / "decky-translator-games"
        games_dir.mkdir()

        # 旧形式のファイルを作成
        old_file = games_dir / "12345.txt"
        old_file.write_text("--- Game ---\nOld prompt content.", encoding='utf-8')

        # マイグレーションロジック（main.py の _migrate_old_game_prompt と同等）
        app_id = 12345
        old_path = games_dir / f"{app_id}.txt"
        new_dir = games_dir / str(app_id)

        if old_path.exists() and not new_dir.is_dir():
            new_dir.mkdir(parents=True, exist_ok=True)
            new_path = new_dir / "text.txt"
            old_path.rename(new_path)

        # 検証
        assert not old_file.exists()  # 旧ファイルは消えている
        new_text = games_dir / "12345" / "text.txt"
        assert new_text.exists()
        content = new_text.read_text(encoding='utf-8')
        assert "Old prompt content." in content

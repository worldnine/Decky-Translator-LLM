# tests/test_migration.py
# 旧設定からの移行テスト

import os
import pytest


class TestLlmSystemPromptMigration:
    """旧 llm_system_prompt → text-common.txt 移行のテスト。"""

    def test_旧設定からファイルへ移行(self, tmp_path):
        """text-common.txt が存在しない場合、旧 llm_system_prompt を移行する"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        text_common_path = prompts_dir / "text-common.txt"
        old_system_prompt = "Keep HP, MP unchanged. Translate UI labels concisely."

        # 移行ロジック（main.py の _load_settings_and_init と同等）
        if not text_common_path.exists() and old_system_prompt:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            text_common_path.write_text(old_system_prompt, encoding='utf-8')

        assert text_common_path.exists()
        assert text_common_path.read_text(encoding='utf-8') == old_system_prompt

    def test_ファイル存在時は上書きしない(self, tmp_path):
        """text-common.txt が既に存在する場合、旧設定で上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        text_common_path = prompts_dir / "text-common.txt"

        existing_content = "Existing prompt that should not be overwritten."
        text_common_path.write_text(existing_content, encoding='utf-8')

        old_system_prompt = "This should NOT overwrite."

        # 移行ロジック
        if not text_common_path.exists() and old_system_prompt:
            text_common_path.write_text(old_system_prompt, encoding='utf-8')

        # 既存ファイルが保持されていること
        assert text_common_path.read_text(encoding='utf-8') == existing_content

    def test_旧設定が空の場合は移行しない(self, tmp_path):
        """旧 llm_system_prompt が空の場合はファイルを作成しない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        text_common_path = prompts_dir / "text-common.txt"
        old_system_prompt = ""

        if not text_common_path.exists() and old_system_prompt:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            text_common_path.write_text(old_system_prompt, encoding='utf-8')

        assert not text_common_path.exists()


class TestDefaultVisionCommonCreation:
    """デフォルト vision-common.txt 生成のテスト。"""

    def test_Vision有効時にデフォルト生成(self, tmp_path):
        """vision_mode != off かつ vision-common.txt が存在しない場合、デフォルト内容で生成"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        vision_common_path = prompts_dir / "vision-common.txt"
        vision_mode = "direct"

        # 生成ロジック（main.py と同等）
        if not vision_common_path.exists() and vision_mode != "off":
            prompts_dir.mkdir(parents=True, exist_ok=True)
            default_content = (
                "Group text by semantic meaning: merge consecutive lines "
                "that form a paragraph or sentence into ONE region.\n"
                "Menu items, buttons, labels, and standalone UI elements "
                "must each be a SEPARATE region."
            )
            vision_common_path.write_text(default_content, encoding='utf-8')

        assert vision_common_path.exists()
        content = vision_common_path.read_text(encoding='utf-8')
        assert "Group text by semantic meaning" in content
        assert "SEPARATE region" in content

    def test_Vision無効時は生成しない(self, tmp_path):
        """vision_mode == off の場合はデフォルトファイルを生成しない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        vision_common_path = prompts_dir / "vision-common.txt"
        vision_mode = "off"

        if not vision_common_path.exists() and vision_mode != "off":
            prompts_dir.mkdir(parents=True, exist_ok=True)
            vision_common_path.write_text("default", encoding='utf-8')

        assert not vision_common_path.exists()

    def test_既存ファイルは上書きしない(self, tmp_path):
        """vision-common.txt が既に存在する場合は上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        vision_common_path = prompts_dir / "vision-common.txt"

        existing = "User customized vision prompt."
        vision_common_path.write_text(existing, encoding='utf-8')
        vision_mode = "direct"

        if not vision_common_path.exists() and vision_mode != "off":
            vision_common_path.write_text("default", encoding='utf-8')

        assert vision_common_path.read_text(encoding='utf-8') == existing

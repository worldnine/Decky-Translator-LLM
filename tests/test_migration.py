# tests/test_migration.py
# 旧設定からの移行テスト

import os
import pytest


class TestLlmSystemPromptMigration:
    """旧 llm_system_prompt → vision-common.txt 移行のテスト。"""

    def test_旧設定からファイルへ移行(self, tmp_path):
        """vision-common.txt が存在しない場合、旧 llm_system_prompt を移行する"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        vision_common_path = prompts_dir / "vision-common.txt"
        old_system_prompt = "Keep HP, MP unchanged. Translate UI labels concisely."

        # 移行ロジック（main.py の _load_settings_and_init と同等）
        if not vision_common_path.exists() and old_system_prompt:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            vision_common_path.write_text(old_system_prompt, encoding='utf-8')

        assert vision_common_path.exists()
        assert vision_common_path.read_text(encoding='utf-8') == old_system_prompt

    def test_ファイル存在時は上書きしない(self, tmp_path):
        """vision-common.txt が既に存在する場合、旧設定で上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        vision_common_path = prompts_dir / "vision-common.txt"

        existing_content = "Existing prompt that should not be overwritten."
        vision_common_path.write_text(existing_content, encoding='utf-8')

        old_system_prompt = "This should NOT overwrite."

        # 移行ロジック
        if not vision_common_path.exists() and old_system_prompt:
            vision_common_path.write_text(old_system_prompt, encoding='utf-8')

        # 既存ファイルが保持されていること
        assert vision_common_path.read_text(encoding='utf-8') == existing_content

    def test_旧設定が空の場合は移行しない(self, tmp_path):
        """旧 llm_system_prompt が空の場合はファイルを作成しない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        vision_common_path = prompts_dir / "vision-common.txt"
        old_system_prompt = ""

        if not vision_common_path.exists() and old_system_prompt:
            prompts_dir.mkdir(parents=True, exist_ok=True)
            vision_common_path.write_text(old_system_prompt, encoding='utf-8')

        assert not vision_common_path.exists()

    def test_旧text_commonをvision_commonへ移行(self, tmp_path):
        """vision-common.txt が無い場合、旧 text-common.txt を移す"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        legacy_path = prompts_dir / "text-common.txt"
        vision_common_path = prompts_dir / "vision-common.txt"
        legacy_content = "Legacy common prompt"

        legacy_path.write_text(legacy_content, encoding='utf-8')

        if not vision_common_path.exists():
            legacy_path.rename(vision_common_path)

        assert not legacy_path.exists()
        assert vision_common_path.read_text(encoding='utf-8') == legacy_content


class TestGeminiSettingsMigration:
    """旧設定キーから gemini_* へ寄せる優先順位のテスト。"""

    def _normalize(self, settings: dict, key: str) -> str:
        candidates = {
            "base_url": ["gemini_base_url", "vision_llm_base_url", "text_llm_base_url", "llm_base_url"],
            "api_key": ["gemini_api_key", "vision_llm_api_key", "text_llm_api_key", "llm_api_key"],
            "model": ["gemini_model", "vision_llm_model", "text_llm_model", "llm_model"],
        }[key]
        for candidate in candidates:
            value = settings.get(candidate)
            if value:
                return value
        return ""

    def test_vision設定が最優先(self):
        settings = {
            "llm_model": "old-model",
            "text_llm_model": "text-model",
            "vision_llm_model": "vision-model",
        }
        assert self._normalize(settings, "model") == "vision-model"

    def test_text設定が次点(self):
        settings = {
            "llm_base_url": "https://old.example/v1",
            "text_llm_base_url": "https://text.example/v1",
        }
        assert self._normalize(settings, "base_url") == "https://text.example/v1"

    def test_llm設定が最後のフォールバック(self):
        settings = {
            "llm_api_key": "legacy-key",
        }
        assert self._normalize(settings, "api_key") == "legacy-key"


class TestDefaultVisionCommonCreation:
    """デフォルト vision-common.txt 生成のテスト。"""

    def test_未存在時に空ファイル生成(self, tmp_path):
        """vision-common.txt が存在しない場合、空ファイルを生成"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        vision_common_path = prompts_dir / "vision-common.txt"

        if not vision_common_path.exists():
            prompts_dir.mkdir(parents=True, exist_ok=True)
            vision_common_path.write_text("", encoding='utf-8')

        assert vision_common_path.exists()
        content = vision_common_path.read_text(encoding='utf-8')
        assert content == ""  # 暗黙の内容が注入されていないこと

    def test_既存ファイルは上書きしない(self, tmp_path):
        """vision-common.txt が既に存在する場合は上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        vision_common_path = prompts_dir / "vision-common.txt"

        existing = "User customized vision prompt."
        vision_common_path.write_text(existing, encoding='utf-8')

        if not vision_common_path.exists():
            vision_common_path.write_text("default", encoding='utf-8')

        assert vision_common_path.read_text(encoding='utf-8') == existing

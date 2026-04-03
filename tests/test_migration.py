# tests/test_migration.py
# 旧設定からの移行テスト — 本番コード (py_modules/migration.py) を直接呼ぶ

import os
import pytest
from py_modules.migration import (
    normalize_gemini_setting,
    migrate_llm_system_prompt,
    ensure_vision_common_file,
)


class TestLlmSystemPromptMigration:
    """旧 llm_system_prompt → vision-common.txt 移行のテスト。"""

    def test_旧設定からファイルへ移行(self, tmp_path):
        """vision-common.txt が存在しない場合、旧 llm_system_prompt を移行する"""
        prompts_dir = str(tmp_path / "decky-translator-prompts")
        old_system_prompt = "Keep HP, MP unchanged. Translate UI labels concisely."

        result = migrate_llm_system_prompt(prompts_dir, old_system_prompt)

        assert result is True
        vision_common_path = os.path.join(prompts_dir, "vision-common.txt")
        assert os.path.exists(vision_common_path)
        with open(vision_common_path, 'r', encoding='utf-8') as f:
            assert f.read() == old_system_prompt

    def test_ファイル存在時は上書きしない(self, tmp_path):
        """vision-common.txt が既に存在する場合、旧設定で上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        vision_common_path = prompts_dir / "vision-common.txt"

        existing_content = "Existing prompt that should not be overwritten."
        vision_common_path.write_text(existing_content, encoding='utf-8')

        result = migrate_llm_system_prompt(str(prompts_dir), "This should NOT overwrite.")

        assert result is False
        assert vision_common_path.read_text(encoding='utf-8') == existing_content

    def test_旧設定が空の場合は移行しない(self, tmp_path):
        """旧 llm_system_prompt が空の場合はファイルを作成しない"""
        prompts_dir = str(tmp_path / "decky-translator-prompts")

        result = migrate_llm_system_prompt(prompts_dir, "")

        assert result is False
        assert not os.path.exists(os.path.join(prompts_dir, "vision-common.txt"))

    def test_旧text_commonをvision_commonへ移行(self, tmp_path):
        """vision-common.txt が無い場合、旧 text-common.txt を移す（ensure_vision_common_file経由）"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        legacy_path = prompts_dir / "text-common.txt"
        legacy_content = "Legacy common prompt"
        legacy_path.write_text(legacy_content, encoding='utf-8')

        content = ensure_vision_common_file(str(prompts_dir))

        assert not legacy_path.exists()
        assert (prompts_dir / "vision-common.txt").exists()
        assert content == legacy_content


class TestGeminiSettingsMigration:
    """旧設定キーから gemini_* へ寄せる優先順位のテスト。"""

    def test_gemini設定が最優先(self):
        settings = {
            "gemini_model": "gemini-model",
            "llm_model": "old-model",
            "text_llm_model": "text-model",
            "vision_llm_model": "vision-model",
        }
        assert normalize_gemini_setting(settings, "model") == "gemini-model"

    def test_vision設定が次点(self):
        settings = {
            "llm_model": "old-model",
            "text_llm_model": "text-model",
            "vision_llm_model": "vision-model",
        }
        assert normalize_gemini_setting(settings, "model") == "vision-model"

    def test_text設定が次点(self):
        settings = {
            "llm_base_url": "https://old.example/v1",
            "text_llm_base_url": "https://text.example/v1",
        }
        assert normalize_gemini_setting(settings, "base_url") == "https://text.example/v1"

    def test_llm設定が最後のフォールバック(self):
        settings = {
            "llm_api_key": "legacy-key",
        }
        assert normalize_gemini_setting(settings, "api_key") == "legacy-key"

    def test_全候補なしでデフォルト(self):
        settings = {}
        assert normalize_gemini_setting(settings, "api_key") == ""
        assert normalize_gemini_setting(settings, "model", default="fallback") == "fallback"

    def test_明示的なFalseが保持される(self):
        """gemini_parallel=False のようなブール値が旧キーにフォールバックしない"""
        settings = {
            "gemini_parallel": False,
            "llm_parallel": True,
        }
        assert normalize_gemini_setting(settings, "parallel", default=True) is False

    def test_明示的な空文字列が保持される(self):
        """gemini_base_url="" は空文字列として保持される"""
        settings = {
            "gemini_base_url": "",
            "llm_base_url": "https://old.example/v1",
        }
        assert normalize_gemini_setting(settings, "base_url") == ""


class TestDefaultVisionCommonCreation:
    """デフォルト vision-common.txt 生成のテスト。"""

    def test_未存在時に空ファイル生成(self, tmp_path):
        """vision-common.txt が存在しない場合、空ファイルを生成"""
        prompts_dir = str(tmp_path / "decky-translator-prompts")

        content = ensure_vision_common_file(prompts_dir)

        vision_common_path = os.path.join(prompts_dir, "vision-common.txt")
        assert os.path.exists(vision_common_path)
        assert content == ""  # 暗黙の内容が注入されていないこと

    def test_既存ファイルは上書きしない(self, tmp_path):
        """vision-common.txt が既に存在する場合は上書きしない"""
        prompts_dir = tmp_path / "decky-translator-prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)
        vision_common_path = prompts_dir / "vision-common.txt"
        existing = "User customized vision prompt."
        vision_common_path.write_text(existing, encoding='utf-8')

        content = ensure_vision_common_file(str(prompts_dir))

        assert content == existing

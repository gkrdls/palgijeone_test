import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from palgijeone.config import DEFAULT_GEMINI_MODEL, load_project_env
from palgijeone.llm_agents import GeminiStructuredClient


class EnvironmentConfigTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.env_file = Path(directory.name) / ".env"
        self.env_file.write_text("GEMINI_API_KEY=local-test-key\n", encoding="utf-8-sig")
        self.env_patch = patch("palgijeone.config.PROJECT_ENV_FILE", self.env_file)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_env_file_loads_from_explicit_project_path(self):
        self.assertNotEqual(self.env_file.parent, Path.cwd())
        load_project_env()
        self.assertEqual(os.environ["GEMINI_API_KEY"], "local-test-key")

    def test_existing_environment_takes_precedence(self):
        os.environ["GEMINI_API_KEY"] = "process-test-key"
        load_project_env()
        self.assertEqual(os.environ["GEMINI_API_KEY"], "process-test-key")

    def test_values_are_not_interpolated(self):
        self.env_file.write_text('GEMINI_API_KEY="literal-${OTHER_KEY}"\n', encoding="utf-8")
        os.environ["OTHER_KEY"] = "do-not-expand"
        load_project_env()
        self.assertEqual(os.environ["GEMINI_API_KEY"], "literal-${OTHER_KEY}")

    def test_missing_env_file_still_allows_environment(self):
        os.environ["GEMINI_API_KEY"] = "process-test-key"
        with patch("palgijeone.config.PROJECT_ENV_FILE", self.env_file.parent / "absent.env"):
            load_project_env()
        self.assertEqual(os.environ["GEMINI_API_KEY"], "process-test-key")

    def test_blank_key_fails_without_sdk_or_network(self):
        self.env_file.write_text("GEMINI_API_KEY=\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "GEMINI_API_KEY"):
            GeminiStructuredClient()

    def test_client_reads_local_key_and_explicit_key_takes_precedence(self):
        constructor = Mock()
        google = ModuleType("google")
        google.genai = SimpleNamespace(Client=constructor)
        with patch.dict(sys.modules, {"google": google}):
            GeminiStructuredClient()
            constructor.assert_called_with(api_key="local-test-key")
            GeminiStructuredClient(api_key="explicit-test-key")
            constructor.assert_called_with(api_key="explicit-test-key")

    def test_client_default_model_and_explicit_override(self):
        google = ModuleType("google")
        google.genai = SimpleNamespace(Client=Mock())
        with patch.dict(sys.modules, {"google": google}):
            self.assertEqual(DEFAULT_GEMINI_MODEL, "gemini-3.5-flash-lite")
            self.assertEqual(GeminiStructuredClient().model_name, DEFAULT_GEMINI_MODEL)
            self.assertEqual(
                GeminiStructuredClient(model_name="custom-model").model_name,
                "custom-model",
            )

    def test_cli_default_model_and_explicit_override(self):
        from palgijeone.cli import main

        for model in (None, "custom-model"):
            with self.subTest(model=model):
                args = ["palgijeone", "--agent-mode", "llm"]
                if model:
                    args.extend(["--model", model])
                with (
                    patch.object(sys, "argv", args),
                    patch("palgijeone.llm_agents.GeminiStructuredClient") as client,
                    patch("palgijeone.cli.CompliancePipeline"),
                    patch("palgijeone.cli.print_flow"),
                ):
                    main()
                    client.assert_called_once_with(model_name=model or DEFAULT_GEMINI_MODEL)


if __name__ == "__main__":
    unittest.main()

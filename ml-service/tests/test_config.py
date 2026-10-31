from __future__ import annotations

import importlib
import json
import unittest
from unittest.mock import patch

from app.config import ConfigError, get_settings, load_settings
import app.config


class TestConfig(unittest.TestCase):
    def setUp(self):
        get_settings.cache_clear()

    def tearDown(self):
        get_settings.cache_clear()

    def test_importing_config_does_not_call_load_dotenv_or_read_env(self):
        with patch("dotenv.load_dotenv") as mock_dotenv:
            importlib.reload(app.config)
            mock_dotenv.assert_not_called()
            # Calling load_env_file explicitly should invoke load_dotenv lazily
            app.config.load_env_file()
            mock_dotenv.assert_called_once()

    def test_default_settings_with_disabled_provider(self):
        env = {"LLM_PROVIDER": "disabled"}
        settings = load_settings(env)
        self.assertEqual(settings.llm_provider, "disabled")
        self.assertFalse(settings.llm_configured)
        self.assertEqual(settings.llm_unavailable_reason, "LLM_PROVIDER is set to 'disabled'")
        self.assertEqual(settings.retrieval_top_k, 5)
        self.assertEqual(settings.http_timeout_s, 20.0)
        self.assertEqual(settings.qdrant_url, "http://localhost:6333")
        self.assertEqual(settings.qdrant_collection, "drug_label_chunks")
        self.assertFalse(settings.allow_builtin_reference_corpus)

    def test_deid_require_ner_defaults_to_true(self):
        env = {"LLM_PROVIDER": "disabled"}
        settings = load_settings(env)
        self.assertTrue(settings.deid_require_ner)
        self.assertEqual(settings.deid_spacy_model, "en_core_web_sm")

    def test_invalid_llm_provider_raises_config_error(self):
        env = {"LLM_PROVIDER": "unsupported_provider"}
        with self.assertRaises(ConfigError) as ctx:
            load_settings(env)
        self.assertIn("LLM_PROVIDER must be one of", str(ctx.exception))

    def test_llm_api_key_absent_from_repr_and_public_summary(self):
        secret_key = "sk-live-super-secret-key-xyz"
        env = {
            "LLM_PROVIDER": "openrouter",
            "LLM_API_KEY": secret_key,
        }
        settings = load_settings(env)
        # Check repr
        repr_str = repr(settings)
        self.assertNotIn(secret_key, repr_str)

        # Check public_summary
        summary = settings.public_summary()
        summary_json = json.dumps(summary)
        self.assertNotIn(secret_key, summary_json)
        self.assertNotIn("llm_api_key", summary)
        self.assertIn("llm_provider", summary)
        self.assertTrue(summary["llm_configured"])


if __name__ == "__main__":
    unittest.main()


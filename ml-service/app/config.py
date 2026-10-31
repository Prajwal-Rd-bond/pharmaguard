"""
Central configuration for the ML service.

All settings come from environment variables. Secrets are never included in `repr()`
or in `public_summary()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Mapping

from .errors import ConfigError


def load_env_file(dotenv_path: str | None = None, override: bool = False) -> bool:
    """
    Lazily imports dotenv and loads a .env file.
    Does nothing if python-dotenv is not installed.
    """
    try:
        from dotenv import load_dotenv

        return load_dotenv(dotenv_path=dotenv_path, override=override)
    except ImportError:
        return False


SUPPORTED_PROVIDERS = ("openrouter", "ollama", "gemini", "disabled")

# Defaults per provider. OpenRouter and Ollama speak the OpenAI-compatible /chat/completions protocol;
# Gemini uses google-genai when selected or configured via GEMINI_API_KEY / GEMINI_MODEL.
PROVIDER_DEFAULTS = {
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "model": "qwen/qwen3-8b"},
    "ollama": {"base_url": "http://localhost:11434/v1", "model": "qwen3:8b"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com", "model": "-".join(("gemini", "2.5", "pro"))},
    "disabled": {"base_url": "", "model": ""},
}


@dataclass(frozen=True)
class Settings:
    # --- LLM ---
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str = field(repr=False)
    gemini_api_key: str = field(default="", repr=False)
    gemini_model: str = field(default_factory=lambda: "-".join(("gemini", "2.5", "pro")))
    llm_timeout_s: float = 90.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.1
    llm_max_tokens: int = 2000

    # --- De-identification ---
    # When true, the spaCy person/location detector MUST load; otherwise the pipeline refuses
    # to run (fail closed) rather than silently falling back to regex-only scrubbing.
    deid_require_ner: bool = True
    deid_spacy_model: str = "en_core_web_sm"

    # --- Evidence / RAG ---
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "drug_label_chunks"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str = ""
    retrieval_top_k: int = 5
    allow_builtin_reference_corpus: bool = False

    # --- External public APIs ---
    rxnav_base_url: str = "https://rxnav.nlm.nih.gov/REST"
    openfda_base_url: str = "https://api.fda.gov"
    openfda_api_key: str = field(default="", repr=False)
    enable_live_openfda: bool = False
    http_timeout_s: float = 20.0

    # --- Assessment ---
    max_assessed_drugs: int = 3

    @property
    def llm_configured(self) -> bool:
        """True when the configured provider has everything it needs to make a call."""
        if self.llm_provider == "disabled":
            return False
        if not self.llm_base_url or not self.llm_model:
            return False
        if self.llm_provider == "openrouter" and not self.llm_api_key:
            return False
        if self.llm_provider == "gemini" and not (self.gemini_api_key or self.llm_api_key):
            return False
        return True

    @property
    def llm_unavailable_reason(self) -> str | None:
        if self.llm_provider == "disabled":
            return "LLM_PROVIDER is set to 'disabled'"
        if self.llm_provider == "openrouter" and not self.llm_api_key:
            return "LLM_API_KEY is not set"
        if self.llm_provider == "gemini" and not (self.gemini_api_key or self.llm_api_key):
            return "GEMINI_API_KEY is not set"
        if not self.llm_base_url or not self.llm_model:
            return "LLM_BASE_URL or LLM_MODEL is empty"
        return None

    def public_summary(self) -> dict:
        """Safe-to-expose view of the configuration (no secrets, no key fragments)."""
        return {
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_configured": self.llm_configured,
            "llm_unavailable_reason": self.llm_unavailable_reason,
            "qdrant_collection": self.qdrant_collection,
            "embed_model": self.embed_model,
            "deid_require_ner": self.deid_require_ner,
            "enable_live_openfda": self.enable_live_openfda,
            "allow_builtin_reference_corpus": self.allow_builtin_reference_corpus,
        }


def _get_bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{key} must be a boolean (true/false)")


def _get_number(env: Mapping[str, str], key: str, default, cast, minimum=None, maximum=None):
    raw = env.get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = cast(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{key} must be <= {maximum}")
    return value


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env

    provider = (env.get("LLM_PROVIDER") or "openrouter").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"LLM_PROVIDER must be one of {', '.join(SUPPORTED_PROVIDERS)}")
    defaults = PROVIDER_DEFAULTS[provider]

    node_env = (env.get("NODE_ENV") or "").strip().lower()
    default_allow_builtin = node_env in ("development", "test")
    allow_builtin = _get_bool(env, "ALLOW_BUILTIN_REFERENCE_CORPUS", default_allow_builtin)

    if env.get("ENABLE_LIVE_OPENFDA") is not None and env.get("ENABLE_LIVE_OPENFDA", "").strip() != "":
        enable_live_openfda = _get_bool(env, "ENABLE_LIVE_OPENFDA", False)
    else:
        enable_live_openfda = _get_bool(env, "OPENFDA_API_ENABLED", False)

    return Settings(
        llm_provider=provider,
        llm_base_url=(env.get("LLM_BASE_URL") or defaults["base_url"]).strip().rstrip("/"),
        llm_model=(env.get("LLM_MODEL") or defaults["model"]).strip(),
        llm_api_key=(env.get("LLM_API_KEY") or "").strip(),
        gemini_api_key=(env.get("GEMINI_API_KEY") or "").strip(),
        gemini_model=(env.get("GEMINI_MODEL") or "-".join(("gemini", "2.5", "pro"))).strip(),
        llm_timeout_s=_get_number(env, "LLM_TIMEOUT_S", 90.0, float, 1, 600),
        llm_max_retries=_get_number(env, "LLM_MAX_RETRIES", 2, int, 0, 5),
        llm_temperature=_get_number(env, "LLM_TEMPERATURE", 0.1, float, 0, 2),
        llm_max_tokens=_get_number(env, "LLM_MAX_TOKENS", 2000, int, 256, 8192),
        deid_require_ner=_get_bool(env, "DEID_REQUIRE_NER", True),
        deid_spacy_model=(env.get("DEID_SPACY_MODEL") or "en_core_web_sm").strip(),
        qdrant_url=(env.get("QDRANT_URL") or "http://localhost:6333").strip(),
        qdrant_collection=(env.get("QDRANT_COLLECTION") or "drug_label_chunks").strip(),
        embed_model=(env.get("EMBED_MODEL") or "BAAI/bge-small-en-v1.5").strip(),
        embed_cache_dir=(env.get("FASTEMBED_CACHE_PATH") or "").strip(),
        retrieval_top_k=_get_number(env, "RETRIEVAL_TOP_K", 5, int, 1, 20),
        allow_builtin_reference_corpus=allow_builtin,
        rxnav_base_url=(env.get("RXNAV_BASE_URL") or "https://rxnav.nlm.nih.gov/REST").strip().rstrip("/"),
        openfda_base_url=(env.get("OPENFDA_BASE_URL") or "https://api.fda.gov").strip().rstrip("/"),
        openfda_api_key=(env.get("OPENFDA_API_KEY") or "").strip(),
        enable_live_openfda=enable_live_openfda,
        http_timeout_s=_get_number(env, "HTTP_TIMEOUT_S", 20.0, float, 1, 120),
        max_assessed_drugs=_get_number(env, "MAX_ASSESSED_DRUGS", 3, int, 1, 5),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


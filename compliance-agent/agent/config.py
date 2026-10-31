from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_base_url: str = Field(..., alias="LLM_BASE_URL")
    llm_api_key: str = Field(..., alias="LLM_API_KEY")
    llm_model: str = Field("gpt-oss-20b", alias="LLM_MODEL")

    embed_base_url: str | None = Field(None, alias="EMBED_BASE_URL")
    embed_api_key: str | None = Field(None, alias="EMBED_API_KEY")
    embed_model: str | None = Field(None, alias="EMBED_MODEL")

    mongo_uri: str = Field(..., alias="MONGO_URI")
    mongo_db: str = Field("compliance", alias="MONGO_DB")

    confluence_base_url: str | None = Field(None, alias="CONFLUENCE_BASE_URL")
    confluence_user: str | None = Field(None, alias="CONFLUENCE_USER")
    confluence_api_token: str | None = Field(None, alias="CONFLUENCE_API_TOKEN")
    confluence_spaces: str = Field("", alias="CONFLUENCE_SPACES")

    input_dir: Path = Field(Path("./data/raw"), alias="INPUT_DIR")
    output_dir: Path = Field(Path("./data/output"), alias="OUTPUT_DIR")
    instructions_path: Path = Field(Path("./config/instructions.md"), alias="INSTRUCTIONS_PATH")
    settings_path: Path = Field(Path("./config/settings.yaml"), alias="SETTINGS_PATH")

    chat_host: str = Field("0.0.0.0", alias="CHAT_HOST")
    chat_port: int = Field(8080, alias="CHAT_PORT")


@lru_cache(maxsize=1)
def settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def yaml_settings() -> dict[str, Any]:
    path = settings().settings_path
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def agent_cfg() -> dict[str, Any]:
    return yaml_settings().get("agent", {})


def indexer_cfg() -> dict[str, Any]:
    return yaml_settings().get("indexer", {})


def chatbot_cfg() -> dict[str, Any]:
    return yaml_settings().get("chatbot", {})

"""Prompt loader — reads JSON assets from disk safely."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from genesis_cognitive.prompts.errors import (
    PromptInvalidJsonError,
    PromptNotFoundError,
    UnsafePromptPathError,
)

_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_SAFE_ID_RE = re.compile(r"^[a-z][a-z0-9\-]{0,127}$")


class CurrentPromptReference(BaseModel):
    """Strict model for current.json — only active_version allowed."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    active_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class PromptLoader:
    """Reads prompt assets from a configured root directory."""

    def __init__(self, prompts_root: Path) -> None:
        self._root = prompts_root.resolve()

    def load_current_version(self, agent_id: str) -> str:
        """Read current.json and return active_version via strict model."""
        self._validate_agent_id(agent_id)
        current_path = self._safe_path(agent_id, "current.json")
        data = self._read_json(current_path)
        try:
            ref = CurrentPromptReference.model_validate_json(json.dumps(data, ensure_ascii=False))
        except PydanticValidationError as e:
            raise PromptInvalidJsonError(internal_cause=e) from e
        return ref.active_version

    def load_prompt(self, agent_id: str, version: str) -> dict[str, Any]:
        """Load a specific versioned prompt JSON."""
        self._validate_agent_id(agent_id)
        self._validate_version(version)
        prompt_path = self._safe_path(agent_id, version, "prompt.json")
        return self._read_json(prompt_path)

    def _validate_agent_id(self, agent_id: str) -> None:
        if not _SAFE_ID_RE.match(agent_id):
            raise UnsafePromptPathError()

    def _validate_version(self, version: str) -> None:
        if not _SEMVER_RE.match(version):
            raise UnsafePromptPathError()

    def _safe_path(self, *parts: str) -> Path:
        """Resolve path and verify it stays within prompts root."""
        # Check for traversal in parts
        for part in parts:
            if ".." in part or "/" in part or "\\" in part:
                raise UnsafePromptPathError()
        candidate = self._root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(self._root):
            raise UnsafePromptPathError()
        return candidate

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise PromptNotFoundError()
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise PromptInvalidJsonError(internal_cause=e) from e
        if not isinstance(data, dict):
            raise PromptInvalidJsonError()
        return data  # noqa: RET504

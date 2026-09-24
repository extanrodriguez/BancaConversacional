"""Prompt registry — loads, validates, and caches prompt versions."""

from pathlib import Path

from genesis_cognitive.prompts.prompt_loader import PromptLoader
from genesis_cognitive.prompts.prompt_validator import PromptValidator
from genesis_cognitive.prompts.prompt_version import PromptVersion


class PromptRegistry:
    """Loads and caches validated prompt versions by agent_id."""

    def __init__(self, prompts_root: Path, schemas_root: Path) -> None:
        self._loader = PromptLoader(prompts_root)
        self._validator = PromptValidator(prompts_root, schemas_root)
        self._cache: dict[tuple[str, str], PromptVersion] = {}

    def get_current(self, agent_id: str) -> PromptVersion:
        """Load the current active version for an agent."""
        version = self._loader.load_current_version(agent_id)
        return self.get(agent_id, version)

    def get(self, agent_id: str, version: str) -> PromptVersion:
        """Load a specific version, using cache if available."""
        key = (agent_id, version)
        if key in self._cache:
            return self._cache[key]

        payload = self._loader.load_prompt(agent_id, version)
        prompt_version = self._validator.validate(payload, agent_id, version)
        self._cache[key] = prompt_version
        return prompt_version

    def clear_cache(self) -> None:
        """Clear the internal cache."""
        self._cache.clear()

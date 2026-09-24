"""T05 — PromptRegistry tests."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from genesis_cognitive.prompts.errors import (
    PromptInvalidJsonError,
    PromptNotFoundError,
    PromptSchemaValidationError,
    PromptVersionMismatchError,
    UnsafePromptPathError,
)
from genesis_cognitive.prompts.prompt_registry import PromptRegistry
from genesis_cognitive.prompts.prompt_version import PromptVersion

PROJECT_ROOT = Path(__file__).parent.parent.parent
PROMPTS_ROOT = PROJECT_ROOT / "prompts"
SCHEMAS_ROOT = PROJECT_ROOT / "schemas"


@pytest.fixture()
def registry() -> PromptRegistry:
    return PromptRegistry(PROMPTS_ROOT, SCHEMAS_ROOT)


class TestLoadCurrent:
    def test_load_current_version(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert isinstance(pv, PromptVersion)

    def test_prompt_id_correct(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.prompt_id == "genesis.turn-decision"

    def test_prompt_version_correct(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.prompt_version == "1.2.0"

    def test_agent_id_correct(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.agent_id == "turn-decision-agent"

    def test_status_draft(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.status == "draft"

    def test_output_schema_ref(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert "turn_interpretation" in pv.output_schema_ref

    def test_evaluation_suite_id(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.evaluation_suite_id == "turn-decision-semantic-v1"

    def test_evaluation_dataset_ref(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert pv.evaluation_dataset_ref == "tests/fixtures/semantic-evaluation-v1.jsonl"


class TestLoadExplicit:
    def test_explicit_version(self, registry: PromptRegistry) -> None:
        pv = registry.get("turn-decision-agent", "1.0.0")
        assert pv.prompt_version == "1.0.0"


class TestImmutability:
    def test_model_frozen(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        with pytest.raises(ValidationError):
            pv.prompt_id = "changed"

    def test_instructions_frozen(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        with pytest.raises(ValidationError):
            pv.instructions.role = "changed"

    def test_collections_are_tuples(self, registry: PromptRegistry) -> None:
        pv = registry.get_current("turn-decision-agent")
        assert isinstance(pv.instructions.objectives, tuple)
        assert isinstance(pv.instructions.rules, tuple)
        assert isinstance(pv.instructions.prohibitions, tuple)


class TestCache:
    def test_cache_returns_same_instance(self, registry: PromptRegistry) -> None:
        pv1 = registry.get_current("turn-decision-agent")
        pv2 = registry.get_current("turn-decision-agent")
        assert pv1 is pv2

    def test_clear_cache(self, registry: PromptRegistry) -> None:
        pv1 = registry.get_current("turn-decision-agent")
        registry.clear_cache()
        pv2 = registry.get_current("turn-decision-agent")
        assert pv1 is not pv2
        assert pv1 == pv2


class TestNegative:
    def test_nonexistent_agent(self, registry: PromptRegistry) -> None:
        with pytest.raises(PromptNotFoundError):
            registry.get_current("nonexistent-agent")

    def test_version_not_semver(self, registry: PromptRegistry) -> None:
        with pytest.raises(UnsafePromptPathError):
            registry.get("turn-decision-agent", "v1.0")

    def test_traversal_dotdot(self, registry: PromptRegistry) -> None:
        with pytest.raises(UnsafePromptPathError):
            registry.get("../etc", "1.0.0")

    def test_traversal_backslash(self, registry: PromptRegistry) -> None:
        with pytest.raises(UnsafePromptPathError):
            registry.get("..\\etc", "1.0.0")

    def test_absolute_path_rejected(self, registry: PromptRegistry) -> None:
        with pytest.raises(UnsafePromptPathError):
            registry.get("/etc/passwd", "1.0.0")

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Invalid JSON in prompt file."""
        agent_dir = tmp_path / "bad-agent" / "1.0.0"
        agent_dir.mkdir(parents=True)
        (agent_dir / "prompt.json").write_text("not json", encoding="utf-8")
        (tmp_path / "bad-agent" / "current.json").write_text(
            '{"active_version": "1.0.0"}', encoding="utf-8"
        )
        # Need schema dir too
        schema_dir = tmp_path / "schemas"
        schema_dir.mkdir()
        # Copy prompt schema
        import shutil

        shutil.copy(PROMPTS_ROOT / "schemas" / "agent_prompt.schema.json", schema_dir)
        # This will fail at JSON parse, not schema
        reg = PromptRegistry(tmp_path, SCHEMAS_ROOT)
        with pytest.raises(PromptInvalidJsonError):
            reg.get_current("bad-agent")

    def test_schema_validation_failure(self, tmp_path: Path) -> None:
        """Prompt that doesn't validate against schema."""
        agent_dir = tmp_path / "bad-agent" / "1.0.0"
        agent_dir.mkdir(parents=True)
        (agent_dir / "prompt.json").write_text('{"invalid": true}', encoding="utf-8")
        (tmp_path / "bad-agent" / "current.json").write_text(
            '{"active_version": "1.0.0"}', encoding="utf-8"
        )
        # Copy prompt schema
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        import shutil

        shutil.copy(PROMPTS_ROOT / "schemas" / "agent_prompt.schema.json", schemas_dir)
        reg = PromptRegistry(tmp_path, SCHEMAS_ROOT)
        with pytest.raises(PromptSchemaValidationError):
            reg.get_current("bad-agent")

    def test_agent_id_mismatch(self, tmp_path: Path) -> None:
        """agent_id in prompt doesn't match directory."""
        agent_dir = tmp_path / "my-agent" / "1.0.0"
        agent_dir.mkdir(parents=True)
        # Load real prompt but change agent_id
        real_prompt = json.loads(
            (PROMPTS_ROOT / "turn-decision-agent" / "1.0.0" / "prompt.json").read_text()
        )
        real_prompt["agent_id"] = "wrong-agent-id"
        (agent_dir / "prompt.json").write_text(json.dumps(real_prompt), encoding="utf-8")
        (tmp_path / "my-agent" / "current.json").write_text(
            '{"active_version": "1.0.0"}', encoding="utf-8"
        )
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        import shutil

        shutil.copy(PROMPTS_ROOT / "schemas" / "agent_prompt.schema.json", schemas_dir)
        reg = PromptRegistry(tmp_path, SCHEMAS_ROOT)
        with pytest.raises(PromptVersionMismatchError):
            reg.get_current("my-agent")

    def test_version_mismatch(self, tmp_path: Path) -> None:
        """prompt_version doesn't match directory version."""
        agent_dir = tmp_path / "my-agent" / "2.0.0"
        agent_dir.mkdir(parents=True)
        real_prompt = json.loads(
            (PROMPTS_ROOT / "turn-decision-agent" / "1.0.0" / "prompt.json").read_text()
        )
        real_prompt["agent_id"] = "my-agent"
        # prompt_version is still 1.0.0 but directory is 2.0.0
        (agent_dir / "prompt.json").write_text(json.dumps(real_prompt), encoding="utf-8")
        (tmp_path / "my-agent" / "current.json").write_text(
            '{"active_version": "2.0.0"}', encoding="utf-8"
        )
        schemas_dir = tmp_path / "schemas"
        schemas_dir.mkdir()
        import shutil

        shutil.copy(PROMPTS_ROOT / "schemas" / "agent_prompt.schema.json", schemas_dir)
        reg = PromptRegistry(tmp_path, SCHEMAS_ROOT)
        with pytest.raises(PromptVersionMismatchError):
            reg.get_current("my-agent")

    def test_dataset_pending_does_not_block(self, registry: PromptRegistry) -> None:
        """Dataset file doesn't exist yet but load succeeds (PENDING_T19)."""
        # The dataset_ref points to tests/fixtures/semantic-evaluation-v1.jsonl
        # which doesn't exist yet — but loading should still succeed
        pv = registry.get_current("turn-decision-agent")
        assert pv.evaluation_dataset_ref == "tests/fixtures/semantic-evaluation-v1.jsonl"

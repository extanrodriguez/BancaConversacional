"""Generate agent_prompt.schema.json for prompt asset validation."""

import json
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def agent_prompt_schema() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://genesis.local/prompts/schemas/agent_prompt.schema.json",
        "title": "Agent Prompt Asset",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "prompt_id",
            "agent_id",
            "prompt_version",
            "status",
            "language",
            "instructions",
            "contracts",
            "capabilities",
            "model_policy",
            "evaluation",
            "foundry",
            "change",
        ],
        "properties": {
            "schema_version": {"const": "1.0"},
            "prompt_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "agent_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "prompt_version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
            "status": {"enum": ["draft", "published", "deprecated"]},
            "language": {"type": "string", "minLength": 2, "maxLength": 16},
            "instructions": {
                "type": "object",
                "additionalProperties": False,
                "required": ["role", "objectives", "rules", "prohibitions"],
                "properties": {
                    "role": {"type": "string", "minLength": 1},
                    "objectives": {"type": "array", "items": {"type": "string"}},
                    "rules": {"type": "array", "items": {"type": "string"}},
                    "prohibitions": {"type": "array", "items": {"type": "string"}},
                },
            },
            "contracts": {
                "type": "object",
                "additionalProperties": False,
                "required": ["input", "output_schema"],
                "properties": {
                    "input": {"type": "string", "minLength": 1},
                    "output_schema": {"type": "string", "minLength": 1},
                },
            },
            "capabilities": {
                "type": "object",
                "additionalProperties": False,
                "required": ["catalog_ref", "skills"],
                "properties": {
                    "catalog_ref": {"type": "string", "minLength": 1},
                    "skills": {"type": "array", "items": {"type": "string"}},
                },
            },
            "model_policy": {
                "type": "object",
                "additionalProperties": False,
                "required": ["model_alias", "structured_output"],
                "properties": {
                    "model_alias": {"type": "string", "minLength": 1},
                    "structured_output": {"type": "boolean"},
                },
            },
            "evaluation": {
                "type": "object",
                "additionalProperties": False,
                "required": ["suite_id", "dataset_ref"],
                "properties": {
                    "suite_id": {"type": "string", "minLength": 1},
                    "dataset_ref": {"type": "string", "minLength": 1},
                },
            },
            "foundry": {
                "type": "object",
                "additionalProperties": False,
                "required": ["deployment_ready", "agent_name"],
                "properties": {
                    "deployment_ready": {"type": "boolean"},
                    "agent_name": {"type": "string", "minLength": 1},
                },
            },
            "change": {
                "type": "object",
                "additionalProperties": False,
                "required": ["reason"],
                "properties": {
                    "reason": {"type": "string", "minLength": 1},
                },
            },
        },
    }


def main() -> None:
    schema = agent_prompt_schema()
    path = PROMPTS_DIR / "schemas" / "agent_prompt.schema.json"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"OK: {path}")


if __name__ == "__main__":
    main()

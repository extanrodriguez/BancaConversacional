"""Add uniqueItems to the required arrays in schemas after generation."""

import json
from pathlib import Path

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


def fix_turn_interpretation() -> None:
    path = SCHEMAS_DIR / "turn_interpretation.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    defs = schema["$defs"]

    # ClarificationRequest
    cr = defs["ClarificationRequest"]["properties"]
    cr["already_known"]["uniqueItems"] = True
    cr["missing_requirements"]["uniqueItems"] = True

    # SemanticAction
    sa = defs["SemanticAction"]["properties"]
    sa["missing_requirements"]["uniqueItems"] = True
    # depends_on already has uniqueItems

    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Fixed turn_interpretation.schema.json")


def fix_intent_resolution() -> None:
    path = SCHEMAS_DIR / "intent_resolution.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    defs = schema["$defs"]

    # ResolvedClarification
    rc = defs["ResolvedClarification"]["properties"]
    rc["already_known"]["uniqueItems"] = True
    rc["missing_requirements"]["uniqueItems"] = True

    # ResolvedAction
    ra = defs["ResolvedAction"]["properties"]
    ra["missing_requirements"]["uniqueItems"] = True
    # depends_on_action_ids already has uniqueItems

    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Fixed intent_resolution.schema.json")


def fix_cognitive_turn_request() -> None:
    path = SCHEMAS_DIR / "cognitive_turn_request.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))

    # Fix language
    schema["properties"]["user_turn"]["properties"]["language"] = {
        "type": "string",
        "minLength": 2,
        "maxLength": 3,
        "pattern": "^[a-z]{2,3}$",
    }

    # Fix locale in channel_context
    schema["properties"]["channel_context"]["properties"]["locale"] = {
        "type": "string",
        "minLength": 2,
        "maxLength": 32,
        "pattern": "^[a-z]{2,3}(-[A-Z]{2})?$",
    }

    # Fix PortfolioProduct balance patterns in $defs
    pp = schema["$defs"]["PortfolioProduct"]["properties"]
    pp["recent_balance"] = {
        "type": ["string", "null"],
        "pattern": "^-?\\d+(\\.\\d+)?$",
    }
    pp["known_reserved_amount"] = {
        "type": ["string", "null"],
        "pattern": "^\\d+(\\.\\d+)?$",
    }

    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("Fixed cognitive_turn_request.schema.json")


if __name__ == "__main__":
    fix_turn_interpretation()
    fix_intent_resolution()
    fix_cognitive_turn_request()

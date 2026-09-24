"""Unit tests for block_movements_as_mutation — no model, no network."""

from genesis_cognitive.router.mutation_guardrail import block_movements_as_mutation


def _action(intent_id: str, amount=None, dest=None) -> list[dict]:
    return [{
        "intent_id": intent_id,
        "detected_entities": {
            "account_ref": "COR001",
            "source_account_ref": None,
            "destination_account_ref": dest,
            "amount": amount,
            "currency": None,
            "knowledge_topic": None,
        },
    }]


def test_movements_with_amount_blocked():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("ACCOUNT_MOVEMENTS_READ", amount="20")
    )
    assert status == "UNSUPPORTED"
    assert actions == []
    assert len(unsup) == 1
    assert "OPERATION_NOT_ENABLED" in unsup[0]["reason"]


def test_movements_with_destination_blocked():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("ACCOUNT_MOVEMENTS_READ", dest="AHO001")
    )
    assert status == "UNSUPPORTED"
    assert actions == []


def test_movements_with_both_blocked():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("ACCOUNT_MOVEMENTS_READ", amount="500", dest="COR001")
    )
    assert status == "UNSUPPORTED"


def test_movements_without_amount_ok():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("ACCOUNT_MOVEMENTS_READ")
    )
    assert status == "VALID_CONTRACT"
    assert len(actions) == 1
    assert unsup == []


def test_balance_read_not_touched():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("ACCOUNT_BALANCE_READ", amount="100")
    )
    assert status == "VALID_CONTRACT"
    assert unsup == []


def test_loan_read_not_touched():
    status, actions, unsup = block_movements_as_mutation(
        "VALID_CONTRACT", _action("LOAN_DETAIL_READ")
    )
    assert status == "VALID_CONTRACT"


def test_non_valid_status_not_touched():
    status, actions, unsup = block_movements_as_mutation(
        "CLARIFICATION_REQUIRED", _action("ACCOUNT_MOVEMENTS_READ", amount="20")
    )
    assert status == "CLARIFICATION_REQUIRED"
    assert unsup == []

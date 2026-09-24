"""Temperature kwargs según deployment (gpt-6-astra no acepta temperature=0)."""

from genesis_cognitive.brain.semantic_mode import (
    azure_chat_options,
    azure_supports_custom_temperature,
)


def test_gpt6_astra_omits_temperature():
    assert azure_supports_custom_temperature("gpt-6-astra") is False
    opts = azure_chat_options(response_format={"type": "json_object"}, temperature=0, deployment="gpt-6-astra")
    assert "temperature" not in opts
    assert opts["response_format"] == {"type": "json_object"}


def test_gpt4o_mini_keeps_temperature():
    assert azure_supports_custom_temperature("gpt-4o-mini") is True
    opts = azure_chat_options(temperature=0, deployment="gpt-4o-mini")
    assert opts["temperature"] == 0

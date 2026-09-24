"""Fix test files to pass tuples where capability_types now expects them."""

from pathlib import Path

# Fix test_capability_catalog.py
p = Path("tests/unit/test_capability_catalog.py")
c = p.read_text(encoding="utf-8")
# CapabilityQueryContext fields
c = c.replace("app_capabilities=[],", "app_capabilities=(),")
c = c.replace("app_capabilities=[],", "app_capabilities=(),")
c = c.replace(
    'orchestrator_capabilities=["core.transfer"],', 'orchestrator_capabilities=("core.transfer",),'
)
c = c.replace("orchestrator_capabilities=[],", "orchestrator_capabilities=(),")

# CapabilityManifest in extensibility test
c = c.replace("required_entities=[],\n", "required_entities=(),\n")
c = c.replace("optional_entities=[],\n", "optional_entities=(),\n")
c = c.replace("required_capabilities=[],", "required_capabilities=(),")
c = c.replace("allowed_channels=[],", "allowed_channels=(),")
c = c.replace('allowed_channels=["ws"],', 'allowed_channels=("ws",),')
c = c.replace(
    'required_entities=["source_account_ref"],', 'required_entities=("source_account_ref",),'
)
p.write_text(c, encoding="utf-8")
print("Fixed test_capability_catalog.py")

# Fix test_types.py
p = Path("tests/unit/test_types.py")
c = p.read_text(encoding="utf-8")
c = c.replace("required_entities=[],", "required_entities=(),")
c = c.replace("optional_entities=[],", "optional_entities=(),")
c = c.replace("required_capabilities=[],", "required_capabilities=(),")
c = c.replace("allowed_channels=[],", "allowed_channels=(),")
c = c.replace('allowed_channels=["ws"],', 'allowed_channels=("ws",),')
c = c.replace(
    'intent_ids=["TRANSFER_BETWEEN_OWN_ACCOUNTS"],',
    'intent_ids=("TRANSFER_BETWEEN_OWN_ACCOUNTS",),',
)
c = c.replace('intent_ids=["XXX"],', 'intent_ids=("XXX",),')
c = c.replace(
    'required_entities=("source_account_ref",),', 'required_entities=("source_account_ref",),'
)  # already correct
p.write_text(c, encoding="utf-8")
print("Fixed test_types.py")

# Fix test_adapters.py
p = Path("tests/unit/test_adapters.py")
c = p.read_text(encoding="utf-8")
c = c.replace("app_capabilities=[],", "app_capabilities=(),")
c = c.replace(
    'orchestrator_capabilities=["core.transfer"],', 'orchestrator_capabilities=("core.transfer",),'
)
c = c.replace("orchestrator_capabilities=[],", "orchestrator_capabilities=(),")
p.write_text(c, encoding="utf-8")
print("Fixed test_adapters.py")

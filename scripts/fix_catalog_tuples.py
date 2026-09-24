"""Fix all list literals in capability_catalog.py to tuples."""

from pathlib import Path

p = Path("src/genesis_cognitive/decision/capability_catalog.py")
c = p.read_text(encoding="utf-8")

# Fix intent_ids
c = c.replace(
    'intent_ids=["BUSINESS_KNOWLEDGE_QUERY"],', 'intent_ids=("BUSINESS_KNOWLEDGE_QUERY",),'
)
c = c.replace('intent_ids=["PORTFOLIO_LIST"],', 'intent_ids=("PORTFOLIO_LIST",),')
c = c.replace('intent_ids=["ACCOUNT_BALANCE_READ"],', 'intent_ids=("ACCOUNT_BALANCE_READ",),')
c = c.replace('intent_ids=["ACCOUNT_MOVEMENTS_READ"],', 'intent_ids=("ACCOUNT_MOVEMENTS_READ",),')
c = c.replace(
    'intent_ids=["TRANSFER_BETWEEN_OWN_ACCOUNTS"],',
    'intent_ids=("TRANSFER_BETWEEN_OWN_ACCOUNTS",),',
)
c = c.replace('intent_ids=["CLARIFICATION_REQUIRED"],', 'intent_ids=("CLARIFICATION_REQUIRED",),')
c = c.replace('intent_ids=["UNKNOWN"],', 'intent_ids=("UNKNOWN",),')

# Fix any remaining lists in the builder
c = c.replace("required_capabilities=[],", "required_capabilities=(),")
c = c.replace("allowed_channels=[],", "allowed_channels=(),")
c = c.replace("optional_entities=[],", "optional_entities=(),")
c = c.replace("required_entities=[],", "required_entities=(),")

p.write_text(c, encoding="utf-8")
print("Fixed all list→tuple in catalog")

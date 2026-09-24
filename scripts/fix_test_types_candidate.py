"""Fix test_types.py to include capability_candidate in CapabilityManifest calls."""

from pathlib import Path

c = Path("tests/unit/test_types.py").read_text(encoding="utf-8")

# First: test_valid
old1 = '''            capability_id="transfer",
            intent_ids=["TRANSFER_BETWEEN_OWN_ACCOUNTS"],
            domain="TRANSFERS"'''
new1 = '''            capability_id="transfer",
            intent_ids=["TRANSFER_BETWEEN_OWN_ACCOUNTS"],
            capability_candidate="TRANSFER",
            domain="TRANSFERS"'''
c = c.replace(old1, new1)

# For the two invalid tests that use capability_id="x"
old2 = '''                capability_id="x",
                intent_ids=["XXX"],
                domain="XX"'''
new2 = '''                capability_id="x",
                intent_ids=["XXX"],
                capability_candidate=None,
                domain="XX"'''
c = c.replace(old2, new2)

Path("tests/unit/test_types.py").write_text(c, encoding="utf-8")
print("Fixed test_types.py capability_candidate")

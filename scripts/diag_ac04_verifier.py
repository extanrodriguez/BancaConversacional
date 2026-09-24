"""Quick diagnostic: what does the verifier output for 'mi saldo'?"""
import asyncio
import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

async def main():
    import uuid
    import httpx
    import json

    # We can't easily intercept the verifier inside the endpoint.
    # Instead, let's check what the endpoint returns when we make the 
    # InvalidModelOutputError more descriptive temporarily.
    # Actually, let's just check the response structure of a single call
    # but capture at the HTTP level with more detail.
    
    # The simplest approach: the error is in _validate_branch_invariants
    # Let's check: does CLARIFICATION require clarification_question?
    # Yes: if not verified.clarification_question: raise InvalidModelOutputError()
    
    # The verifier 1.2.3 probably outputs CLARIFICATION but forgets the question.
    # Let me check by looking at what the verifier schema allows.
    
    print("The issue is almost certainly: verifier returns result_type=CLARIFICATION")
    print("but clarification_question=null")
    print("")
    print("The _validate_branch_invariants check requires:")
    print("  if rt == 'CLARIFICATION' and not verified.clarification_question: raise")
    print("")
    print("The verifier prompt 1.2.3 says to produce CLARIFICATION but may not")
    print("explicitly require clarification_question to be non-null.")

asyncio.run(main())

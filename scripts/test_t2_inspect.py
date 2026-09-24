"""Test T2: POST /inspect with customer context from SQLite."""
import httpx
import json

BASE = "http://localhost:8000"

# Test 1: Default customer (CUST001)
print("=== Test 1: Default customer (Hola) ===")
r = httpx.post(f"{BASE}/inspect", json={"question": "Hola"}, timeout=30)
d = r.json()
print(f"HTTP: {r.status_code}")
print(f"status: {d.get('status')}")
print(f"customer_context: {d.get('customer_context')}")
print()

# Test 2: Explicit CUST002
print("=== Test 2: CUST002 explicit ===")
r2 = httpx.post(f"{BASE}/inspect", json={"question": "Hola", "customer_id": "CUST002"}, timeout=30)
d2 = r2.json()
print(f"HTTP: {r2.status_code}")
print(f"status: {d2.get('status')}")
print(f"customer_context: {d2.get('customer_context')}")
print()

# Test 3: Nonexistent customer
print("=== Test 3: NONEXISTENT customer ===")
r3 = httpx.post(f"{BASE}/inspect", json={"question": "Hola", "customer_id": "NONEXISTENT"}, timeout=30)
d3 = r3.json()
print(f"HTTP: {r3.status_code}")
print(f"status: {d3.get('status')}")
print(f"customer_context: {d3.get('customer_context')}")

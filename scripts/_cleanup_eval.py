from pathlib import Path
path = Path("scripts/potenciacion_eval.py")
text = path.read_text(encoding="utf-8")
# Ensure default is PENDING_EVALUATION (never rewrite to FAIL_INTERPRETATION)
old = (
    'return "FAIL_INTERPRETATION", {\n'
    '        "facets": {"no_oracle_match": "Y"},\n'
    '        "detail": "Sin aserciones tipadas; nonempty no aprueba",\n'
    '        "oracle_version": ORACLE_VERSION,\n'
    "    }"
)
new = (
    'return "PENDING_EVALUATION", {\n'
    '        "facets": {"no_oracle_match": "Y"},\n'
    '        "detail": "Sin aserciones tipadas; no se aprueba ni se cuenta como fallo funcional",\n'
    '        "oracle_version": ORACLE_VERSION,\n'
    "    }"
)
if old in text:
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("restored PENDING")
else:
    print("already PENDING or different text")

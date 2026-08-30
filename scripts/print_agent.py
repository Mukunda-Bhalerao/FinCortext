"""Pretty-print an AgentOutput JSON payload from stdin (verification helper)."""

import json
import sys

o = json.load(sys.stdin)
print("agent:", o["agent_id"], "| entity:", o["entity_id"])
print("status:", o["status"], "| score:", o["score"], "| signal:", o["signal"], "| confidence:", o["confidence"])
prov = o.get("provenance", {})
print("peers_with_prices:", prov.get("peers_with_prices", "<n/a>"))
if "data_preparation" in prov:
    print("data_preparation:", json.dumps(prov["data_preparation"]))
if "articles_stored" in prov:
    print("articles_stored:", prov["articles_stored"], "| articles_relevant:", prov.get("articles_relevant"))
for f in o["factors"]:
    print(f"  factor {f['name']:<18} available={f['available']} value={f['value']}")
print("rationale:", o["rationale"][:200])

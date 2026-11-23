"""Layer 3 (agents) demo: call the Feline Wellness A2A agent through APIM.

    python scripts/test-a2a.py --path wellness-agent "How much water should my 4kg cat drink?"
    python scripts/test-a2a.py --direct https://<a2a-app>.azurewebsites.net "..."   # bypass APIM

Copy the exact "Runtime base URL" / "Agent card URL" from the APIM A2A API overview if they differ
(use --runtime-url / --card-url).
"""
import argparse
import json
import os
import pathlib
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).parents[1] / "agents" / "procode" / ".env")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("question", nargs="?", default="My cat is bored at night. Any enrichment ideas?")
    p.add_argument("--path", default="wellness-agent", help="Base path of the A2A API in APIM")
    p.add_argument("--runtime-url")
    p.add_argument("--card-url")
    p.add_argument("--direct", help="Backend base URL to bypass APIM")
    p.add_argument("--key", default=os.getenv("APIM_GOLD_KEY"))
    args = p.parse_args()

    if args.direct:
        base, headers = args.direct.rstrip("/"), {}
    else:
        base = os.environ["APIM_GATEWAY_URL"].rstrip("/") + "/" + args.path
        headers = {"Ocp-Apim-Subscription-Key": args.key, "x-agent-id": "demo-cli"}
    card_url = args.card_url or f"{base}/.well-known/agent-card.json"
    runtime_url = args.runtime_url or f"{base}/"

    card = httpx.get(card_url, headers=headers, timeout=30)
    print(f"GET agent card -> {card.status_code}")
    if card.is_success:
        c = card.json()
        print(f"  name: {c.get('name')}\n  url : {c.get('url')}  (rewritten to the gateway when served by APIM)")

    payload = {
        "jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "message/send",
        "params": {"message": {"role": "user", "messageId": str(uuid.uuid4()),
                               "parts": [{"kind": "text", "text": args.question}]}},
    }
    r = httpx.post(runtime_url, json=payload, headers=headers, timeout=60)
    print(f"POST message/send -> {r.status_code}")
    try:
        body = r.json()
        parts = body.get("result", {}).get("parts", [])
        print("\n" + ("\n".join(x.get("text", "") for x in parts) or json.dumps(body, indent=2)))
    except ValueError:
        print(r.text[:500])


if __name__ == "__main__":
    main()

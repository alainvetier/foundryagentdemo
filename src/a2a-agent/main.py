"""Dr. Meowgan Freeman - Feline Wellness Advisor, exposed over the A2A protocol (JSON-RPC).

Minimal, dependency-light A2A server for the demo:
- GET  /.well-known/agent-card.json   (and legacy /.well-known/agent.json)
- POST /                               JSON-RPC 2.0, method "message/send"
Model calls go through the APIM "models" API, so the agent itself is governed by the AI gateway.
"""
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import AzureOpenAI

PUBLIC_URL = os.getenv("A2A_PUBLIC_URL", "http://localhost:8000").rstrip("/")
CHAT_MODEL = os.getenv("CHAT_MODEL", "gpt-4.1-mini")

SYSTEM_PROMPT = (
    "You are Dr. Meowgan Freeman, the feline wellness advisor at Whisker Works, a store run by techie cats. "
    "You give practical, safe, general cat-care guidance (nutrition, hydration, enrichment, sleep, grooming). "
    "Keep answers under 120 words, friendly, with at most one cat pun. "
    "Always recommend a licensed veterinarian for symptoms, injuries or medication questions. "
    "You do not sell products and you never invent prices."
)

AGENT_CARD = {
    "protocolVersion": "0.3.0",
    "name": "Dr. Meowgan Freeman - Feline Wellness Advisor",
    "description": "Gives general cat wellness guidance (nutrition, hydration, enrichment, sleep). Not a substitute for a vet.",
    "url": f"{PUBLIC_URL}/",
    "preferredTransport": "JSONRPC",
    "version": "1.0.0",
    "provider": {"organization": "Whisker Works", "url": "https://example.com/whisker-works"},
    "capabilities": {"streaming": False, "pushNotifications": False},
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "cat-wellness-advice",
            "name": "Cat wellness advice",
            "description": "General guidance on feeding, hydration, enrichment, sleep and grooming.",
            "tags": ["cats", "wellness", "nutrition"],
            "examples": ["How much water should my 4kg cat drink per day?", "My cat is bored at night, any ideas?"],
        }
    ],
}

app = FastAPI(title="Feline Wellness A2A Agent")
_client: AzureOpenAI | None = None


def client() -> AzureOpenAI:
    global _client
    if _client is None:
        _client = AzureOpenAI(
            azure_endpoint=os.environ["APIM_MODELS_ENDPOINT"],
            api_key=os.environ["APIM_MODELS_KEY"],
            api_version="2024-10-21",
            default_headers={"x-client-app": "a2a-wellness-agent"},
        )
    return _client


def rpc_error(req_id, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


@app.get("/healthz")
def healthz():
    return {"status": "purring"}


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
def agent_card():
    return AGENT_CARD


@app.post("/")
async def jsonrpc(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return rpc_error(None, -32700, "Parse error")
    req_id = body.get("id")
    if body.get("method") != "message/send":
        return rpc_error(req_id, -32601, f"Method not supported: {body.get('method')}")

    message = (body.get("params") or {}).get("message") or {}
    text = "\n".join(p.get("text", "") for p in message.get("parts", []) if p.get("kind", "text") == "text").strip()
    if not text:
        return rpc_error(req_id, -32602, "Message must contain at least one text part")

    completion = client().chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
        max_tokens=300,
    )
    answer = completion.choices[0].message.content or ""

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "kind": "message",
            "role": "agent",
            "messageId": str(uuid.uuid4()),
            "contextId": message.get("contextId") or str(uuid.uuid4()),
            "parts": [{"kind": "text", "text": answer}],
        },
    })

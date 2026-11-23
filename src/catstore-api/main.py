"""Whisker Works - store API + storefront for the demo.

In-memory data; resets on every restart (good for demos).
"""
import json
import logging
import math
import os
import random
import uuid
from datetime import datetime, timezone
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity import DefaultAzureCredential
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from openai import APIError, BadRequestError, RateLimitError

from foundry_errors import throttle_retry_delay

BASE_DIR = Path(__file__).parent
logger = logging.getLogger(__name__)
PRODUCTS: dict[str, dict] = {p["id"]: p for p in json.loads((BASE_DIR / "data" / "products.json").read_text())}

CAT_FACTS = [
    "Cats sleep 12-16 hours a day, which is roughly the uptime of a well-run CI pipeline.",
    "A group of cats is called a clowder. A group of cats on a keyboard is called a deployment.",
    "Cats have 32 muscles in each ear and still choose not to hear you.",
    "A cat's purr vibrates between 25 and 150 Hz, a frequency associated with bone healing.",
    "Cats can rotate their ears 180 degrees - perfect for listening to two stand-ups at once.",
    "Each cat's nose print is unique, like a fingerprint or an API key.",
    "Cats cannot taste sweetness. They prefer their feedback salty.",
]

ORDERS: dict[str, dict] = {
    "ORD-1001": {"orderId": "ORD-1001", "customerName": "Grace Hopper", "status": "shipped", "shippingCountry": "US",
                 "items": [{"productId": "WW-002", "quantity": 1}], "total": 34.99, "createdAt": "2026-09-28T10:00:00Z"},
    "ORD-1002": {"orderId": "ORD-1002", "customerName": "Ada Lovelace", "status": "processing", "shippingCountry": "GB",
                 "items": [{"productId": "WW-001", "quantity": 2}, {"productId": "WW-006", "quantity": 3}], "total": 59.45, "createdAt": "2026-10-01T15:30:00Z"},
    "ORD-1003": {"orderId": "ORD-1003", "customerName": "Linus Pawvalds", "status": "delivered", "shippingCountry": "FI",
                 "items": [{"productId": "WW-005", "quantity": 1}], "total": 89.00, "createdAt": "2026-09-15T08:12:00Z"},
}

app = FastAPI(title="Whisker Works Store API", version="1.0.0")


class OrderItem(BaseModel):
    productId: str
    quantity: int = Field(ge=1, le=20)


class OrderRequest(BaseModel):
    customerName: str = Field(min_length=1, max_length=100)
    shippingCountry: str = Field(min_length=2, max_length=2)
    items: list[OrderItem] = Field(min_length=1, max_length=10)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    previousResponseId: str | None = None


@app.get("/healthz")
def healthz():
    return {"status": "purring"}


@app.get("/api/products")
def list_products(category: str | None = None, q: str | None = Query(default=None, max_length=100)):
    items = list(PRODUCTS.values())
    if category:
        items = [p for p in items if p["category"] == category.lower()]
    if q:
        ql = q.lower()
        items = [p for p in items if ql in p["name"].lower() or ql in p["description"].lower() or ql in " ".join(p["tags"])]
    return items


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    product = PRODUCTS.get(product_id.upper())
    if not product:
        raise HTTPException(404, f"Product {product_id} not found. Even our cats looked under the sofa.")
    return product


@app.get("/api/inventory/{product_id}")
def check_inventory(product_id: str):
    product = get_product(product_id)
    stock = product["stock"]
    status = "out_of_stock" if stock == 0 else "low_stock" if stock < 5 else "in_stock"
    return {"productId": product["id"], "stock": stock, "status": status}


@app.post("/api/orders", status_code=201)
def place_order(order: OrderRequest):
    total = 0.0
    for item in order.items:
        product = get_product(item.productId)
        if product["stock"] < item.quantity:
            raise HTTPException(409, f"Not enough stock for {product['name']} (available: {product['stock']}).")
        total += product["price"] * item.quantity
    for item in order.items:
        PRODUCTS[item.productId.upper()]["stock"] -= item.quantity
    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
    ORDERS[order_id] = {
        "orderId": order_id,
        "customerName": order.customerName,
        "status": "processing",
        "shippingCountry": order.shippingCountry.upper(),
        "items": [i.model_dump() for i in order.items],
        "total": round(total, 2),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    return ORDERS[order_id]


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    order = ORDERS.get(order_id.upper())
    if not order:
        raise HTTPException(404, f"Order {order_id} not found.")
    return order


@app.get("/api/catfacts/random")
def random_cat_fact():
    return {"fact": random.choice(CAT_FACTS)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    """Storefront chat widget -> Foundry agent (uses the web app's managed identity)."""
    endpoint = os.getenv("FOUNDRY_PROJECT_ENDPOINT")
    agent_name = os.getenv("STOREFRONT_AGENT_NAME")
    if not endpoint or not agent_name:
        raise HTTPException(503, "Chat is not configured yet.")
    kwargs = {"previous_response_id": req.previousResponseId} if req.previousResponseId else {}
    try:
        with DefaultAzureCredential() as credential, \
             AIProjectClient(endpoint=endpoint, credential=credential) as project, \
             project.get_openai_client() as client:
            response = client.responses.create(
                input=req.message,
                extra_body={"agent_reference": {"name": agent_name, "type": "agent_reference"}},
                **kwargs,
            )
    except (APIError, AzureError) as exc:
        logger.warning(
            "Storefront chat failed: type=%s upstream_status=%s request_id=%s",
            exc.__class__.__name__, getattr(exc, "status_code", None), getattr(exc, "request_id", None),
        )
        delay = throttle_retry_delay(exc, 0) if isinstance(exc, (BadRequestError, RateLimitError)) else None
        if delay is not None:
            seconds = math.ceil(delay)
            raise HTTPException(
                429, f"Whiskers is busy with other shoppers. Please wait {seconds} seconds before trying again.",
                headers={"Retry-After": str(seconds)},
            ) from exc
        raise HTTPException(502, "Whiskers could not reach the concierge service. Please try again shortly.") from exc
    return {"reply": response.output_text, "responseId": response.id}


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/")
def storefront():
    return FileResponse(BASE_DIR / "static" / "index.html")

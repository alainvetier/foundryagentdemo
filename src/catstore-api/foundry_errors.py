"""Classify Foundry throttling, including APIM MCP errors wrapped as HTTP 400."""
import re

from openai import BadRequestError, RateLimitError


def throttle_retry_delay(error: BadRequestError | RateLimitError, retry: int) -> float | None:
    body = error.body if isinstance(error.body, dict) else {}
    detail = body.get("error", body)
    if not isinstance(detail, dict):
        detail = {}
    message = str(detail.get("message", ""))
    wrapped_mcp_throttle = (
        detail.get("code") == "tool_user_error"
        and "remote server" in message.lower()
        and re.search(r"\b429\b", message) is not None
    )
    if not isinstance(error, RateLimitError) and not wrapped_mcp_throttle:
        return None

    delay = float(min(2 ** (retry + 1), 30))
    header = error.response.headers.get("retry-after", "")
    if re.fullmatch(r"\d+(?:\.\d+)?", header):
        delay = max(delay, float(header) + 1)
    hint = re.search(r"try again in\s+(\d+(?:\.\d+)?)\s+seconds?", message, re.IGNORECASE)
    if hint:
        delay = max(delay, float(hint.group(1)) + 1)
    return delay

"""
GubaCheck - MODEL LIST AND PRICES (OpenRouter public catalogue)
=========================================================================
    models()          tool-capable models with US$ per 1M input / output tokens
    price_of(model)   (input, output) per 1M tokens, or None if unknown

READS      https://openrouter.ai/api/v1/models (public, no key), cached in
           memory for an hour.
RETURNS    an empty list when offline; callers fall back to config prices.
WATCH OUT  the live call also asks OpenRouter for the billed cost of each
           request (core/backends.py); that figure wins over price x tokens.
=========================================================================
"""
import json
import time
import urllib.request

URL = "https://openrouter.ai/api/v1/models"
_CACHE = {"at": 0, "models": []}


def models():
    if _CACHE["models"] and time.time() - _CACHE["at"] < 3600:
        return _CACHE["models"]
    try:
        data = json.load(urllib.request.urlopen(URL, timeout=15))["data"]
    except Exception:
        return _CACHE["models"]
    out = []
    for m in data:
        p = m.get("pricing") or {}
        try:
            pin, pout = float(p.get("prompt", 0)) * 1e6, float(p.get("completion", 0)) * 1e6
        except (TypeError, ValueError):
            continue
        if "tools" not in (m.get("supported_parameters") or []) or pin < 0 or pout < 0:
            continue                      # the agent needs native tool calling
        out.append({"id": m["id"], "name": m.get("name", m["id"]), "pin": round(pin, 4), "pout": round(pout, 4)})
    out.sort(key=lambda m: m["id"])
    _CACHE.update(at=time.time(), models=out)
    return out


def price_of(model):
    for m in models():
        if m["id"] == model:
            return m["pin"], m["pout"]
    return None

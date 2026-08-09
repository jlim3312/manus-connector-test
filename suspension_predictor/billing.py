"""Minimal tenant / API-key / quota store standing in for real subscription
billing. This is intentionally simple (a JSON file, in-memory counters) so
the rest of the app has a concrete gating point to build real billing
against later -- see README 'Subscription / SaaS roadmap' for the Stripe
integration plan. Do not use this module as-is in production: usage counts
are lost on restart and there is no persistence layer or webhook handling.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "api_keys.json"
_lock = threading.Lock()


class QuotaExceeded(Exception):
    pass


class InvalidApiKey(Exception):
    pass


def _load() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _save(data: dict) -> None:
    with open(_DATA_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def get_tenant(api_key: str) -> dict:
    data = _load()
    tenant = data.get("tenants", {}).get(api_key)
    if tenant is None:
        raise InvalidApiKey(f"Unknown API key")
    return tenant


def check_and_increment_usage(api_key: str) -> dict:
    """Raises InvalidApiKey / QuotaExceeded, otherwise increments and
    returns the updated tenant record."""
    with _lock:
        data = _load()
        tenant = data.get("tenants", {}).get(api_key)
        if tenant is None:
            raise InvalidApiKey("Unknown API key")
        quota = tenant.get("monthly_quota")
        used = tenant.get("usage_this_period", 0)
        if quota is not None and used >= quota:
            raise QuotaExceeded(
                f"Monthly quota of {quota} predictions exhausted for plan '{tenant.get('plan')}'."
            )
        tenant["usage_this_period"] = used + 1
        _save(data)
        return tenant

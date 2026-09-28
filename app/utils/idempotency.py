"""Idempotency helpers shared by the booking and payment flows."""

import hashlib
import json
from typing import Any


def request_fingerprint(*parts: Any) -> str:
    """Stable sha256 over the semantic request fields.

    Stored alongside an Idempotency-Key so a replayed key with a *different*
    request is detected and rejected (Stripe-style) instead of silently
    returning the first result. Callers pass normalised values (e.g. the
    UTC-normalised appointment, "success" for an omitted outcome) so
    equivalent requests fingerprint identically.
    """
    payload = json.dumps(list(parts), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

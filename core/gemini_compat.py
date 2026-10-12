"""Compatibility helpers for google-genai versions with unstable async client cleanup."""

from __future__ import annotations

import asyncio
from typing import Any


async def generate_content(client: Any, **kwargs: Any) -> Any:
    """Run the sync google-genai client off the event loop.

    Some google-genai releases schedule an async BaseApiClient.aclose task even
    when the aio client is not fully initialized. Using the synchronous client
    in a worker thread avoids that cleanup path while preserving bot latency.
    """
    return await asyncio.to_thread(client.models.generate_content, **kwargs)

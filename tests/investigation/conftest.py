"""Shared fixtures for investigation tests."""
from __future__ import annotations

import pytest
import asyncio

@pytest.fixture(scope="session")
def event_loop():
    """Use a single event loop for all async tests."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    yield loop
    loop.close()

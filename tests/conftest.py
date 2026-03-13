"""Test configuration and shared fixtures."""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()

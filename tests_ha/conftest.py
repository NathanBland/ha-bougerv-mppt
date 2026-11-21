"""Fixtures for tests that run inside Home Assistant (pytest-homeassistant-custom-component)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True, scope="session")
def no_bluez_history():
    """The plugin fakes a Linux adapter; on macOS reading BlueZ history fails, so stub it."""
    with patch("bluetooth_adapters.systems.linux.LinuxAdapters.history", {}):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return None


@pytest.fixture(autouse=True)
def auto_enable_bluetooth(enable_bluetooth: None) -> None:
    return None

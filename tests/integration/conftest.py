"""Pytest config for tests/test_integration_setup.py.

Only needed for that real-HA integration test (not the lightweight
tests/test_payload.py suite, which has no Home Assistant dependency).
"""
import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield

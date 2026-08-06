"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import socket
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_CN_API_KEY",
    "ZHIPU_API_KEY",
    "ZHIPU_CN_API_KEY",
    "MINIMAX_API_KEY",
    "MINIMAX_CN_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        # `or` not a .get default: an env var present but empty (e.g. a key left
        # blank in a .env copied from .env.example) must still get the placeholder.
        monkeypatch.setenv(env_var, os.environ.get(env_var) or "placeholder")


@pytest.fixture(autouse=True)
def _isolate_config():
    """Reset the global dataflows config before and after each test.

    ``set_config`` merges (it never clears keys absent from the override), so a
    test that sets e.g. ``tool_vendors`` would otherwise leak into later tests
    and make routing behavior order-dependent. Replace the global outright so
    every test starts from a clean DEFAULT_CONFIG.
    """
    import copy

    import tradingagents.dataflows.config as config_module
    import tradingagents.default_config as default_config

    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)
    yield
    config_module._config = copy.deepcopy(default_config.DEFAULT_CONFIG)


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client


# ---------------------------------------------------------------------------
# No unit test may touch the network.
#
# 36 tests in this suite were making live HTTPS calls and passing anyway, because
# the code under test treats a failed fetch as inconclusive and falls back. That
# is worse than a red test: they passed for the wrong reason, they were flaky
# whenever an exchange was unreachable, and every full run hammered MEXC and
# twitterapi.io. Blocking the socket turns each leak into an immediate, named
# failure instead of a silent one.
#
# A test that genuinely needs a live service belongs under the `integration`
# marker, which is exempt below.
_REAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def _no_network(request):
    if request.node.get_closest_marker("integration"):
        yield
        return

    def blocked(self, address):
        raise AssertionError(
            f"{request.node.name} tried to open a network connection to "
            f"{address}. Unit tests must stub their I/O — mock the fetch, or mark "
            f"the test `@pytest.mark.integration` if it truly needs the service.")

    socket.socket.connect = blocked
    try:
        yield
    finally:
        socket.socket.connect = _REAL_CONNECT

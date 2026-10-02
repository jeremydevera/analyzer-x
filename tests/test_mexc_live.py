"""Live MEXC checks. Network-bound, so they are marked integration and are
deselected from a normal unit run — a module-level unit mark would drag a
two-minute exchange sweep into every fast test run.
"""

import pytest

from tradingagents.dataflows import mexc

pytestmark = pytest.mark.integration

def test_live_host_resolves():
    assert mexc.resolve_host() in mexc.DEFAULT_HOSTS



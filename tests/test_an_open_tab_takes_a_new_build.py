"""An open tab reloads onto a new build of the screen by itself.

Operator, Sep 29, 2026: "again why is my ui not refreshing, i thought
everyting you change will reflect to web autoamtically since t his is react".
Every panel's NUMBERS poll the API; the screen's CODE is a production build,
and a tab kept the build it loaded — the new "Paper · all time" tile and the
Watcher pager were invisible in a tab opened before the restart."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "webapp"


def _read(p):
    return (ROOT / p).read_text("utf-8")


def test_both_halves_carry_the_same_build_id():
    cfg = _read("next.config.ts")
    assert "generateBuildId: async () => BUILD_ID" in cfg
    assert "env: { NEXT_PUBLIC_BUILD_ID: BUILD_ID }" in cfg


def test_the_server_says_its_build_at_request_time():
    route = _read("src/app/build-version/route.ts")
    assert '".next", "BUILD_ID"' in route and 'dynamic = "force-dynamic"' in route
    assert '"no-store"' in route
    # never under /api: next.config proxies that prefix to the Python API
    assert not (ROOT / "src/app/api").exists()


def test_every_page_carries_the_checker():
    assert "<NewVersionReload />" in _read("src/app/layout.tsx")


def test_it_never_reloads_over_an_unsaved_edit_or_a_field_being_typed_in():
    chk = _read("src/components/NewVersionReload.tsx")
    assert "if (!hasUnsaved() && !busyTyping()) window.location.reload();" in chk
    assert "else setBehind(true);" in chk and "Reload now" in chk
    grid = _read("src/components/trade/StrategiesGrid.tsx")
    assert 'markUnsaved("strategies", dirty)' in grid

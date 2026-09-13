"""A process meant to outlive its starter must actually be cut loose.

Bought on `Sep 13, 2026 4:02pm`: the operator's app had been dead for **28
hours 18 minutes** and nothing on the machine said so. The API was restarted
at `Sep 12, 2026 10:38am` by a helper script that passed
`CREATE_NEW_PROCESS_GROUP` and NOT `DETACHED_PROCESS`, so it stayed a child of
the shell that made it and died with that shell at `11:44am` — mid-request,
no error, the last log line a normal `GET /api/health 200 OK`.

Windows needs BOTH flags. One of them alone is the bug, and it is invisible:
the process starts, answers, and looks perfect until its parent goes away.

**Why a grep did not find the sites:** `rows_index` and `storage_months` spell
the flags as `0x00000008 | 0x00000200` and only NAME them in a comment, so
searching for `DETACHED_PROCESS` finds the prose and misses the code, while
searching the hex misses `start.py` and `live_ingest`, which use the names.
This walks the AST and accepts either spelling — the rule is about the VALUE.
"""
import ast
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200

FILES = sorted(
    [REPO / "start.py"]
    + list((REPO / "tradingagents").rglob("*.py"))
)


def _flag_value(node) -> int | None:
    """Fold `A | B` into a number, whether spelled as hex or as attributes."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Attribute):
        return {"DETACHED_PROCESS": DETACHED_PROCESS,
                "CREATE_NEW_PROCESS_GROUP": CREATE_NEW_PROCESS_GROUP,
                "CREATE_NO_WINDOW": 0x08000000}.get(node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left, right = _flag_value(node.left), _flag_value(node.right)
        if left is None or right is None:
            return None
        return left | right
    return None


def _called_name(node) -> str:
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr
    return getattr(f, "id", "")


def _creationflag_assignments():
    """Every place this repo starts a LONG-LIVED child with Windows flags.

    Deliberately NOT every `creationflags` in the repo. A blocking
    `subprocess.run(["wmic", ...], creationflags=CREATE_NO_WINDOW)` hides a
    console window on a call that returns in milliseconds — demanding
    DETACHED_PROCESS there would be a false failure, and the first version of
    this test produced exactly one (portable.py:199). The rule is about
    children that must OUTLIVE their starter, which in this repo means
    `Popen`, the `kwargs` dict built for a `Popen`, and the shared
    `DETACHED` spread.
    """
    out = []
    for path in FILES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        # does this file ever start a long-lived child at all?
        spawns = any(isinstance(n, ast.Call) and _called_name(n) == "Popen"
                     for n in ast.walk(tree))
        for node in ast.walk(tree):
            # Popen(..., creationflags=...)
            if isinstance(node, ast.Call) and _called_name(node) == "Popen":
                for kw in node.keywords:
                    if kw.arg == "creationflags":
                        out.append((path, node.lineno, _flag_value(kw.value)))
            # kwargs["creationflags"] = ... , in a file that goes on to Popen
            if isinstance(node, ast.Assign) and spawns:
                for t in node.targets:
                    if (isinstance(t, ast.Subscript)
                            and isinstance(t.slice, ast.Constant)
                            and t.slice.value == "creationflags"):
                        out.append((path, node.lineno, _flag_value(node.value)))
            # the shared DETACHED spread in portable.py
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "DETACHED":
                        for n2 in ast.walk(node.value):
                            if (isinstance(n2, ast.Dict)
                                    and any(isinstance(k, ast.Constant)
                                            and k.value == "creationflags"
                                            for k in n2.keys)):
                                for k, v in zip(n2.keys, n2.values, strict=False):
                                    if (isinstance(k, ast.Constant)
                                            and k.value == "creationflags"):
                                        out.append((path, node.lineno,
                                                    _flag_value(v)))
    return out


def test_the_probe_actually_finds_the_spawn_sites():
    """A probe that finds ZERO of what it looks for has verified nothing."""
    found = _creationflag_assignments()
    assert len(found) >= 4, \
        f"only found {len(found)} creationflags sites — the walker is broken"


@pytest.mark.parametrize(
    "path,line,value",
    [pytest.param(p, ln, v, id=f"{p.name}:{ln}")
     for p, ln, v in _creationflag_assignments()],
)
def test_every_detached_spawn_sets_BOTH_windows_flags(path, line, value):
    """CREATE_NEW_PROCESS_GROUP alone does NOT detach.

    It only separates the process from its parent's Ctrl-C. The child still
    belongs to the parent's console and job, so when the parent's tree is
    cleaned up — `taskkill /T`, a closed terminal, a harness reaping a
    background task — the child dies with it. That is what took the API down
    for 28 hours on Sep 12, 2026.
    """
    assert value is not None, (
        f"{path.name}:{line} sets creationflags to something this test cannot "
        f"fold into a number — spell it as literals or named constants")
    assert value & CREATE_NEW_PROCESS_GROUP, (
        f"{path.name}:{line} is missing CREATE_NEW_PROCESS_GROUP — a Ctrl-C "
        f"in the parent would reach this child")
    assert value & DETACHED_PROCESS, (
        f"{path.name}:{line} is missing DETACHED_PROCESS — this child is NOT "
        f"detached and will die with whoever started it, exactly like the API "
        f"did on Sep 12, 2026 at 11:44am")

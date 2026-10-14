# Load a .env file at package import so every entry point (the runner, the
# API, the jobs) sees the same environment. find_dotenv(usecwd=True) walks
# from the CWD; load_dotenv defaults to override=False, so it never clobbers
# values the caller has already exported.
#
# The LLM pieces that used to sit here (the `.env.enterprise` Azure keys and
# the langchain/langgraph warning filters) went with the AI analysts on
# Oct 02, 2026: "remove the new crypto, analysis and llm models completly,
# i will not use them anymore".
try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
except ImportError:
    pass

# THE ENGINE AS IT STOOD WHEN THIS PROCESS STARTED (Oct 14, 2026). Taken
# before any engine module loads, so it is never NEWER than the code this
# process runs: room_replay labels its cached trade lists with it — labelled
# from the files when first asked, hours later, a back end started on old
# code could file old-rule lists under the new code's name.
ENGINE_FILES_AT_START: dict = {}
try:
    from pathlib import Path as _Path

    for _f in sorted(_Path(__file__).resolve().parent.glob("*.py")):
        if _f.name in ("auto_trader.py", "market_sweep.py", "backtest_report.py",
                       "strategy_keys.py") or _f.name.startswith("signals"):
            _st = _f.stat()
            ENGINE_FILES_AT_START[_f.name] = (_st.st_size, _st.st_mtime_ns)
except OSError:
    pass

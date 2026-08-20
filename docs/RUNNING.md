# Running the app

```bash
./start.sh            # React UI on 8503, Python API on 8787 behind it
./start.sh status     # which ports are held, and whether the API answers
./start.sh stop       # free both ports (by PID, never by name)
```

Then open **http://localhost:8503** — one url. The UI proxies `/api/*` to the
API process, so there is no second port to remember and no CORS.

## What runs where

| Piece | Port | What it is |
|---|---|---|
| UI | 8503 | Next.js (TailAdmin), production build |
| API | 8787 | FastAPI over the same modules the tests cover |
| Runner | none | detached process, `auto_trader`; started/stopped from Auto Trade |
| Jobs | none | detached processes: candle download, backtest, analysis runs |

The runner and every job are separate processes on purpose: closing the
browser, restarting the UI, or rebuilding does not stop a live position, a
sweep, or an analysis.

## Front-end development

```bash
cd webapp && npm run dev      # port 3000, same /api proxy, hot reload
```

## The old Streamlit app

`app.py` is still in the tree and can be run on a different port if a
comparison is needed:

```bash
.venv/bin/streamlit run app.py --server.headless true --server.port 8504
```

It reads the same files (`~/.tradingagents/`), so both see one truth. Nothing
in the React app depends on it.

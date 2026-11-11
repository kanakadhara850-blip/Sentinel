# SENTINEL – Real-Time Financial Transaction Risk Platform (all-in-one)

```
sentinel-risk-platform/
├── run.py                 <- start everything (backend + frontend)
├── frontend_server.py     <- local static server (mimics vercel.json routes)
├── backend/               <- FastAPI + TCP ingest + ML pipeline + SQLite (see backend/README.md)
├── frontend/              <- web dashboard (public/index.html, public/app.html, vercel.json)
├── database/              <- schemas, CSV exports, DATABASE.md
│                             (live DB used at runtime: backend/data/risk.db)
└── .vscode/               <- launch + task configs
```

## Run in VS Code
1. File > Open Folder... > `sentinel-risk-platform`
2. Terminal > New Terminal, then (Python 3.10+):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
   pip install -r backend/requirements.txt
   python run.py
   ```
   Or press **F5** and choose *Run everything (backend + frontend)*.
3. Browser opens at `http://localhost:3000/login?ws=ws://localhost:8000/ws/events`
   Login: `admin@sentinel.demo` / `sentinel-demo`
4. Optional: second terminal -> `cd backend && python scripts/simulate.py live --rate 5 --fraud-rate 0.15` to stream traffic.

Ports: frontend 3000, API 8000 (docs at /docs), TCP ingest 9009.
Tests: `cd backend && pytest -q`. Frontend deploys to Vercel from `frontend/` as before.

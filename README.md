# final trade

## Frontend

```bash
cd frontend
corepack pnpm install
corepack pnpm dev
```

Use `frontend/.env.example` to switch between mock APIs and backend APIs.

## Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

# Backend API (FastAPI)

## Setup

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Health

```bash
curl http://127.0.0.1:8000/health
```

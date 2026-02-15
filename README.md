# Final Trade

Language:
- English: `README.md`
- 中文: `README.zh-CN.md`

Integrated stock workflow:
- Screener funnel
- Wyckoff-based buy signals
- Simulated trading loop
- Portfolio and review analytics
- AI analysis records

Backend: FastAPI  
Frontend: React + Vite + Ant Design + React Query

## Recent Updates (2026-02)

- Replaced direct "simulate buy" on Signals/Screener pages with "Add to Pending Buy List".
- Added centralized pending order workflow on Trade page.
- Pending buy sizing now supports:
  - `lots`
  - `amount`
  - `position (%)`
- Portfolio color convention changed to:
  - gain = red
  - loss = green
- Review stats now support date axis:
  - `sell` (by sell date)
  - `buy` (by buy date)
- Signals filter updated:
  - `Active` excludes expiring signals
  - `Expiring` is a separate status
- Fixed signal expiry logic issue that could mark almost all signals as expiring.
- Improved AI analysis table UI to avoid text overlap on zoom.

## Repository Structure

```text
backend/    FastAPI services and local state
frontend/   React application
docs/       Architecture and usage docs
```

## One-Click Start

### Windows

```powershell
.\start.bat
```

or

```powershell
.\start-dev.ps1
```

Default behavior:
- Stops stale processes on ports `8000` and `4173`
- Starts backend on `127.0.0.1:8000`
- Starts frontend on `127.0.0.1:4173`
- Opens browser automatically
- Writes logs to `runtime-logs/`

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

## Manual Start

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev:host
```

## Core Features

### Screener and Signals

- 4-step screener funnel with per-step pools
- Trend-pool mode and full-market mode for signals
- Signal scoring and Wyckoff event context
- Navigation from signal row to chart and trade page

### Sim Trading

- A-share style T+1 simulation
- 100-share lot enforcement
- Place/cancel/settle/reset order flow
- Configurable cost model:
  - commission
  - minimum commission
  - stamp tax
  - transfer fee
  - slippage
- FIFO lot matching on sell

### Pending Buy Workflow

- Add candidates from:
  - Signals page
  - Screener page
- Manage and submit drafts on Trade page
- Per-draft editable sizing mode and value
- Batch submit selected drafts into real sim orders

### Portfolio and Review

- Portfolio snapshot and positions
- Realized/unrealized PnL
- Review stats with buy/sell date axis
- Charts:
  - equity curve
  - drawdown curve
  - monthly returns
- Export: Excel / CSV / PDF

### AI Records

- AI analysis record list with filters
- Link to stock chart annotation page
- Record deletion and local sync
- Improved table readability and layout stability

## Common API Endpoints

- `POST /api/screener/run`
- `GET /api/screener/runs/{run_id}`
- `GET /api/screener/latest-run`
- `GET /api/signals`
- `POST /api/sim/orders`
- `GET /api/sim/orders`
- `GET /api/sim/fills`
- `POST /api/sim/orders/{order_id}/cancel`
- `POST /api/sim/settle`
- `POST /api/sim/reset`
- `GET /api/sim/config`
- `PUT /api/sim/config`
- `GET /api/sim/portfolio`
- `GET /api/review/stats` (`date_axis=sell|buy`)
- `POST /api/system/sync-market-data`
- `GET /api/system/storage`

## Frontend Environment Variables

- `VITE_ENABLE_MSW=true` enable mock API mode
- `VITE_ENABLE_MSW=false` use real backend API
- `VITE_API_BASE_URL` optional API base URL override
- `VITE_API_PROXY_TARGET` Vite proxy target (default `http://127.0.0.1:8000`)

## Local Persistence

- App state: `~/.tdx-trend/app_state.json`
- Sim state: `~/.tdx-trend/sim_state.json`

## Build and Test

### Backend

```bash
python -m pytest backend/tests/test_api.py -q
```

### Frontend

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

## First Run Checklist

1. Start services with `start.bat` (Windows) or `start.sh` (Linux/macOS).
2. Confirm backend is reachable at `http://127.0.0.1:8000/health`.
3. Open frontend at `http://127.0.0.1:4173`.
4. Run one screener pass, then open Signals/Trade/Review pages in sequence.

## Troubleshooting

- Page not loading:
  - ensure backend is running (`/health` returns 200)
  - ensure frontend dev server is running on `4173`
  - hard refresh browser (`Ctrl+F5`)
- Data load failed:
  - check `tdx_data_path` and market data source in Settings
  - trigger `POST /api/system/sync-market-data`
- Port occupied:
  - backend: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8001`
  - frontend: `npm run dev -- --port 4174`
- Need full reset:
  - stop services
  - clear frontend cache (`frontend/node_modules/.vite`)
  - restart with `start.bat` or `start.sh`

## Additional Docs

- `docs/QUICKSTART.md`
- `docs/ARCHITECTURE.md`
- `docs/VERIFICATION.md`

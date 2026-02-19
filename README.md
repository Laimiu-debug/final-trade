# Final Trade

Language:
- English: `README.md`
- Chinese: `README.zh-CN.md`

Integrated stock workflow:
- Screener funnel
- Wyckoff-based buy signals
- Simulated trading loop
- Portfolio and review analytics
- AI analysis records

Backend: FastAPI  
Frontend: React + Vite + Ant Design + React Query

## Recent Updates (2026-02-19)

- Review workspace upgrades:
  - Share card panel now persists search keyword, selected stock, notes, and selection history.
  - Market index panel now persists selected indices, market mood, and mood notes.
- Pending buy workflow centralization:
  - Signals/Screener "simulate buy" now goes through Trade-page pending list.
  - Pending buy sizing supports `lots`, `amount`, and `position (%)`.
- Review and signals refinements:
  - Review stats support `date_axis=sell|buy`.
  - Signals status split between `Active` and `Expiring`.
  - Fixed signal expiry logic edge case.
- UI updates:
  - Portfolio color convention: gain = red, loss = green.
  - AI analysis table readability improved under browser zoom.

## Repository Structure

```text
backend/        FastAPI services and local persistence
frontend/       React application
docs/           Architecture and usage docs
runtime-logs/   Dev startup logs
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

Default behavior (`start-dev.ps1`):
- Stops stale processes on ports `8010`, `8000`, and `4173`
- Starts backend on `127.0.0.1:8010`
- Starts frontend on `127.0.0.1:4173`
- Automatically sets `VITE_API_PROXY_TARGET` to current backend URL
- Opens browser automatically
- Writes logs to `runtime-logs/`

Optional parameters:

```powershell
.\start-dev.ps1 -BackendUrl "http://127.0.0.1:8011" -FrontendUrl "http://127.0.0.1:4174" -NoBrowser
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

Note: current `start.sh` starts backend on `127.0.0.1:8000`.

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

If backend is not `8000`, set proxy target before starting frontend:

```powershell
$env:VITE_API_PROXY_TARGET="http://127.0.0.1:8010"
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
- Configurable costs: commission, minimum commission, stamp tax, transfer fee, slippage
- FIFO lot matching on sell

### Pending Buy Workflow

- Add candidates from Signals page and Screener page
- Manage/edit/submit drafts on Trade page
- Per-draft sizing mode and value
- Batch submit selected drafts into real sim orders

### Portfolio and Review

- Portfolio snapshot and positions
- Realized/unrealized PnL
- Review stats with buy/sell date axis
- Daily/weekly review records
- Review tags and per-fill tag assignments
- Market index watch panel with saved index selection
- Share card workspace with local state persistence
- Export: Excel / CSV / PDF

### AI Records

- AI analysis record list with filters
- Prompt preview and provider test endpoint
- Link to stock chart annotation page
- Record deletion and local sync

## Common API Endpoints

- `GET /health`
- `POST /api/screener/run`
- `GET /api/screener/runs/{run_id}`
- `GET /api/screener/latest-run`
- `GET /api/signals`
- `GET /api/stocks/{symbol}/candles`
- `GET /api/stocks/{symbol}/intraday`
- `GET /api/stocks/{symbol}/analysis`
- `PUT /api/stocks/{symbol}/annotations`
- `POST /api/stocks/{symbol}/ai-analyze`
- `GET /api/stocks/{symbol}/ai-prompt-preview`
- `GET /api/ai/records`
- `DELETE /api/ai/records`
- `POST /api/ai/providers/test`
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
- `GET /api/review/daily`
- `GET /api/review/daily/{date}`
- `PUT /api/review/daily/{date}`
- `DELETE /api/review/daily/{date}`
- `GET /api/review/weekly`
- `GET /api/review/weekly/{week_label}`
- `PUT /api/review/weekly/{week_label}`
- `DELETE /api/review/weekly/{week_label}`
- `GET /api/review/tags`
- `POST /api/review/tags/{tag_type}`
- `DELETE /api/review/tags/{tag_type}/{tag_id}`
- `GET /api/review/fill-tags`
- `GET /api/review/fill-tags/{order_id}`
- `PUT /api/review/fill-tags/{order_id}`
- `GET /api/review/tag-stats`
- `GET /api/market/news`
- `GET /api/config`
- `PUT /api/config`
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
2. Confirm backend is reachable:
   - Windows default: `http://127.0.0.1:8010/health`
   - Linux/macOS `start.sh`: `http://127.0.0.1:8000/health`
3. Open frontend at `http://127.0.0.1:4173`.
4. Run one screener pass, then open Signals, Trade, and Review pages in sequence.

## Troubleshooting

- Page not loading:
  - ensure backend is running (`/health` returns 200)
  - ensure frontend dev server is running on `4173`
  - hard refresh browser (`Ctrl+F5`)
- Data load failed:
  - check `tdx_data_path` and market data source in Settings
  - trigger `POST /api/system/sync-market-data`
- Backend started but frontend API requests fail:
  - check backend port
  - set `VITE_API_PROXY_TARGET` to your backend URL before `npm run dev:host`
- Port occupied:
  - backend: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8011`
  - frontend: `npm run dev -- --port 4174`
- Need full reset:
  - stop services
  - clear frontend cache (`frontend/node_modules/.vite`)
  - restart with `start.bat` or `start.sh`

## Additional Docs

- `docs/QUICKSTART.md`
- `docs/ARCHITECTURE.md`
- `docs/VERIFICATION.md`

# final-trade

通达信趋势选股 + 威科夫信号 + 模拟交易闭环项目（前后端一体）。

## 已实现能力

### 1) 选股与信号
- 四步筛选流程（Screener）
- 待买信号（威科夫增强）：
  - 趋势池后置 / 全市场扫描双模式
  - 事件、阶段、评分、风险提示
  - 与 K 线页、交易页联动

### 2) 模拟交易（MVP）
- A 股 T+1 规则（仅多头）
- 100 股整手校验
- 下单、挂单、撤单、自动结算、手动补结
- 成本模型可配置并持久化：
  - 佣金（含最低佣金）
  - 印花税（卖出）
  - 过户费
  - 滑点
- FIFO 批次卖出匹配
- 本地 JSON 持久化：`~/.tdx-trend/sim_state.json`

### 3) 持仓与复盘
- 持仓页：
  - 总资产/现金/市值/已实现/未实现盈亏/挂单数
  - 可卖数量、市值、盈亏额
  - 快捷卖出
- 复盘页：
  - 默认近 90 天 + 自定义日期区间（按卖出日）
  - 权益曲线、回撤曲线、月度收益
  - Top/Bottom 交易 + 明细分页
  - 导出 Excel / CSV / PDF（PDF 中文字体防乱码）

## 项目结构

```text
backend/   FastAPI + 本地状态引擎
frontend/  React + Vite + Ant Design + React Query
```

## 快速启动

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 可选：AkShare 日线同步（无行情 API 时）

```bash
cd backend
pip install -r requirements-akshare.txt
python scripts/sync_akshare_daily.py --symbols 600519,300750,601899
```

缓存目录：

`~/.tdx-trend/akshare/daily/*.csv`

后端在 TDX `.day` 文件不可用时，会自动回退读取该缓存。

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 前端环境变量

- `VITE_ENABLE_MSW=true`：启用 mock 接口
- `VITE_ENABLE_MSW=false`：走真实后端
- `VITE_API_BASE_URL`：可选，默认走 Vite `/api` 代理
- `VITE_API_PROXY_TARGET`：开发代理目标，默认 `http://127.0.0.1:8000`

## 关键接口（模拟交易/复盘）

- `POST /api/sim/orders`
- `GET /api/sim/orders`
- `GET /api/sim/fills`
- `POST /api/sim/orders/{order_id}/cancel`
- `POST /api/sim/settle`
- `POST /api/sim/reset`
- `GET /api/sim/config`
- `PUT /api/sim/config`
- `GET /api/sim/portfolio`
- `GET /api/review/stats`

## 测试与构建

### 后端

```bash
python -m pytest backend/tests/test_api.py -q
```

### 前端

```bash
cd frontend
npm run typecheck
npm run test
npm run build
```

## PDF 中文字体

已使用 `frontend/public/fonts/LXGWWenKai-Regular.ttf`，避免中文导出乱码回归。

## Persistence Notes

- System config / AI records / annotations are persisted at `~/.tdx-trend/app_state.json`.
- Sim trading / portfolio / review state is persisted at `~/.tdx-trend/sim_state.json`.
- Runtime endpoint: `GET /api/system/storage` can be used to inspect local state paths and cache status.

## AkShare Incremental Sync

Default behavior is incremental per symbol (only fetches dates after the latest local row).

```bash
cd backend
python scripts/sync_akshare_daily.py --all-market --limit 300
```

Force full-history refresh:

```bash
python scripts/sync_akshare_daily.py --symbols 600519 --full-history --start-date 2024-01-01
```

## Baostock Incremental Sync (Home page button uses this)

```bash
cd backend
pip install -r requirements-baostock.txt
python scripts/sync_baostock_daily.py --all-market --limit 300 --mode incremental
```

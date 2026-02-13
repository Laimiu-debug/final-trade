# final-trade

通达信趋势选股 + 威科夫待买信号 + 模拟交易闭环（前后端一体）项目。

## 功能概览

### 1) 选股与信号
- 四步选股漏斗（分步运行、池子查看、导出）
- 待买信号（威科夫增强）
  - 趋势池后置 / 全市场扫描双模式
  - 阶段、事件、评分、风险提示
  - 与 K 线页、交易页联动

### 2) 模拟交易（MVP）
- A 股 T+1，仅多头
- 100 股整手校验
- 下单、挂单、撤单、自动结算、手动补结
- 成本模型可配置（佣金、最低佣金、印花税、过户费、滑点）
- FIFO 卖出批次匹配

### 3) 持仓与复盘
- 持仓页：总资产/现金/持仓市值/已实现盈亏/未实现盈亏/挂单数
- 复盘页：近 90 天默认区间 + 自定义区间（按卖出日）
- 图表：权益曲线、回撤曲线、月度收益
- 导出：Excel / CSV / PDF（中文字体已处理）

### 4) 数据与持久化
- 系统配置 + AI 记录 + 标注：持久化到本地 JSON
- 模拟交易账户状态：持久化到本地 JSON
- 行情支持 TDX 日线 + 本地 CSV 行情目录回退

## 项目结构

```text
backend/   FastAPI + 本地状态与数据同步
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

### 前端

```bash
cd frontend
npm install
npm run dev
```

## 行情数据更新（推荐 Baostock）

### 方式 A：首页一键更新（推荐）
- 在首页（选股漏斗页）点击：`一键增量更新行情（Baostock）`
- 该按钮调用后端接口：`POST /api/system/sync-market-data`
- 默认是增量模式，并会回补最近几天，避免“当天有数据但未刷新”的问题

### 方式 B：命令行同步

#### Baostock（推荐）

```bash
cd backend
pip install -r requirements-baostock.txt
python scripts/sync_baostock_daily.py --all-market --limit 300 --mode incremental
```

#### AkShare（可选）

```bash
cd backend
pip install -r requirements-akshare.txt
python scripts/sync_akshare_daily.py --all-market --limit 300
```

CSV 默认目录：

`~/.tdx-trend/akshare/daily/*.csv`

## 本地持久化文件

- 系统配置 / AI记录 / 个股标注：`~/.tdx-trend/app_state.json`
- 模拟交易 / 持仓 / 复盘状态：`~/.tdx-trend/sim_state.json`
- 运行时状态检查接口：`GET /api/system/storage`

## 前端环境变量

- `VITE_ENABLE_MSW=true`：启用 mock 接口
- `VITE_ENABLE_MSW=false`：调用真实后端
- `VITE_API_BASE_URL`：可选，默认走 Vite `/api` 代理
- `VITE_API_PROXY_TARGET`：开发代理目标（默认 `http://127.0.0.1:8000`）

## 常用接口

- `POST /api/screener/run`
- `GET /api/screener/runs/{run_id}`
- `GET /api/signals`
- `POST /api/system/sync-market-data`
- `GET /api/system/storage`
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

已使用 `frontend/public/fonts/LXGWWenKai-Regular.ttf`，避免 PDF 导出中文乱码。

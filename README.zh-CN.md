# Final Trade

语言版本：
- English: `README.md`
- 中文：`README.zh-CN.md`

Final Trade 是一个面向 A 股研究与模拟执行的一体化系统，包含：
- 选股漏斗
- 基于威科夫事件的待买信号
- 模拟交易闭环
- 持仓与复盘统计
- AI 分析记录

后端：FastAPI  
前端：React + Vite + Ant Design + React Query

## 最近更新（2026-02）

- 待买信号与选股漏斗页面的“模拟买入”改为“加入待买单”。
- 模拟交易页新增统一待成交单管理与提交流程。
- 待买单支持三种仓位方式：
  - `lots`（手数）
  - `amount`（金额）
  - `position (%)`（仓位百分比）
- 持仓盈亏颜色改为：
  - 盈利 = 红色
  - 亏损 = 绿色
- 复盘统计支持两种日期轴：
  - `sell`（按卖出日）
  - `buy`（按买入日）
- 信号状态筛选调整：
  - `有效` 不再包含临期
  - `临期` 独立展示
- 修复信号到期逻辑，避免大量信号被误判为临期。
- 优化 AI 分析表格在缩放场景下的重叠问题。

## 目录结构

```text
backend/    FastAPI 服务与本地状态管理
frontend/   React 前端应用
docs/       架构与使用文档
```

## 一键启动

### Windows

```powershell
.\start.bat
```

或

```powershell
.\start-dev.ps1
```

默认行为：
- 自动清理占用 `8000` 和 `4173` 端口的旧进程
- 启动后端：`127.0.0.1:8000`
- 启动前端：`127.0.0.1:4173`
- 自动打开浏览器
- 日志写入 `runtime-logs/`

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

## 手动启动

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
npm run dev:host
```

## 核心功能

### 选股与信号

- 4 步漏斗筛选，每步独立股票池
- 待买信号支持趋势池后置与全市场扫描
- 信号评分与威科夫事件上下文
- 可从信号直接跳转到 K 线标注与交易页

### 模拟交易

- A 股 T+1 规则模拟
- 100 股整数手校验
- 下单 / 撤单 / 补结 / 重置流程
- 交易成本可配置：
  - 佣金
  - 最低佣金
  - 印花税
  - 过户费
  - 滑点
- 卖出按 FIFO 匹配持仓批次

### 待买单工作流

- 可从以下页面加入待买单：
  - 待买信号
  - 选股漏斗
- 在模拟交易页统一管理并提交
- 每条待买单可独立调整仓位方式和数值
- 支持批量提交为真实模拟订单

### 持仓与复盘

- 持仓快照与持仓明细
- 已实现盈亏与浮动盈亏
- 复盘统计支持买入/卖出日期轴
- 图表：
  - 权益曲线
  - 回撤曲线
  - 月度收益
- 支持导出：Excel / CSV / PDF

### AI 分析记录

- AI 分析记录列表与筛选
- 关联股票图表标注页
- 本地记录删除与同步
- 表格可读性与布局稳定性优化

## 常用 API

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
- `GET /api/review/stats`（`date_axis=sell|buy`）
- `POST /api/system/sync-market-data`
- `GET /api/system/storage`

## 前端环境变量

- `VITE_ENABLE_MSW=true`：启用 Mock API
- `VITE_ENABLE_MSW=false`：连接真实后端
- `VITE_API_BASE_URL`：可选，覆盖 API 基地址
- `VITE_API_PROXY_TARGET`：Vite 代理目标（默认 `http://127.0.0.1:8000`）

## 本地持久化

- 应用状态：`~/.tdx-trend/app_state.json`
- 模拟状态：`~/.tdx-trend/sim_state.json`

## 构建与测试

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

## 首次使用流程

1. 运行 `start.bat`（Windows）或 `start.sh`（Linux/macOS）启动前后端。
2. 访问 `http://127.0.0.1:8000/health`，确认后端健康检查通过。
3. 打开 `http://127.0.0.1:4173` 进入前端。
4. 先执行一次选股漏斗，再进入待买信号、模拟交易、复盘统计页面联调检查。

## 常见问题排查

- 页面打不开：
  - 确认后端已启动（`/health` 返回 200）
  - 确认前端开发服务运行在 `4173`
  - 浏览器强刷（`Ctrl+F5`）
- 数据加载失败：
  - 检查设置中的 `tdx_data_path` 与行情数据源
  - 调用 `POST /api/system/sync-market-data` 同步行情
- 端口冲突：
  - 后端：`uvicorn app.main:app --reload --host 127.0.0.1 --port 8001`
  - 前端：`npm run dev -- --port 4174`
- 需要完全重置：
  - 停止所有服务
  - 清理前端缓存目录 `frontend/node_modules/.vite`
  - 重新使用 `start.bat` 或 `start.sh` 启动

## 相关文档

- `docs/QUICKSTART.md`
- `docs/ARCHITECTURE.md`
- `docs/VERIFICATION.md`

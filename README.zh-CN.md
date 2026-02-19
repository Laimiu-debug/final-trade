# Final Trade

语言版本：
- English: `README.md`
- 中文：`README.zh-CN.md`

一体化股票研究与交易流程：
- 选股漏斗
- 基于威科夫事件的待买信号
- 模拟交易闭环
- 持仓与复盘分析
- AI 分析记录

后端：FastAPI  
前端：React + Vite + Ant Design + React Query

## 最近更新（2026-02-19）

- 复盘工作台升级：
  - 个股分享卡片支持持久化：搜索关键词、选中股票、笔记、历史选择记录。
  - 大盘指数面板支持持久化：已选指数、市场情绪、情绪备注。
- 待买单流程统一：
  - 信号页/选股页的“模拟买入”统一改为“加入待买单”，在交易页集中提交。
  - 待买单支持三种仓位方式：`lots`、`amount`、`position (%)`。
- 复盘与信号优化：
  - 复盘统计支持 `date_axis=sell|buy`。
  - 信号状态拆分为 `Active` 与 `Expiring`。
  - 修复信号到期判断边界问题。
- 界面优化：
  - 持仓盈亏颜色规范：盈利=红色，亏损=绿色。
  - AI 分析表格在浏览器缩放场景下可读性提升。

## 仓库结构

```text
backend/        FastAPI 服务与本地持久化
frontend/       React 前端应用
docs/           架构与使用文档
runtime-logs/   开发启动日志
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

`start-dev.ps1` 默认行为：
- 清理占用 `8010`、`8000`、`4173` 的旧进程
- 启动后端：`127.0.0.1:8010`
- 启动前端：`127.0.0.1:4173`
- 自动设置 `VITE_API_PROXY_TARGET` 到当前后端地址
- 自动打开浏览器
- 日志写入 `runtime-logs/`

可选参数：

```powershell
.\start-dev.ps1 -BackendUrl "http://127.0.0.1:8011" -FrontendUrl "http://127.0.0.1:4174" -NoBrowser
```

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

注意：当前 `start.sh` 默认后端端口为 `127.0.0.1:8000`。

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

如果后端不在 `8000` 端口，请先设置代理目标：

```powershell
$env:VITE_API_PROXY_TARGET="http://127.0.0.1:8010"
npm run dev:host
```

## 核心功能

### 选股与信号

- 4 步漏斗选股，每步独立股票池
- 待买信号支持趋势池与全市场扫描
- 信号评分与威科夫事件上下文
- 从信号行跳转到图表和交易页

### 模拟交易

- A 股 T+1 规则模拟
- 100 股整手校验
- 下单 / 撤单 / 结算 / 重置流程
- 成本模型可配置：佣金、最低佣金、印花税、过户费、滑点
- 卖出按 FIFO 匹配持仓批次

### 待买单工作流

- 可从信号页、选股页加入待买单
- 在交易页统一管理、编辑、提交
- 每条待买单可独立调整仓位模式和值
- 支持批量提交为真实模拟订单

### 持仓与复盘

- 持仓快照与持仓明细
- 已实现/浮动盈亏统计
- 复盘统计支持买入/卖出日期轴
- 日复盘、周复盘记录
- 复盘标签与成交标签分配
- 大盘指数监控面板（支持本地记忆）
- 个股分享卡片工作台（支持本地状态持久化）
- 导出：Excel / CSV / PDF

### AI 记录

- AI 分析记录列表与筛选
- 提示词预览与 Provider 连通性测试
- 关联个股图表标注页
- 记录删除与本地同步

## 常用 API 端点

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
- `GET /api/review/stats`（`date_axis=sell|buy`）
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

## 前端环境变量

- `VITE_ENABLE_MSW=true`：启用 Mock API
- `VITE_ENABLE_MSW=false`：连接真实后端
- `VITE_API_BASE_URL`：可选，覆盖 API 基础地址
- `VITE_API_PROXY_TARGET`：Vite 代理目标（默认 `http://127.0.0.1:8000`）

## 本地持久化

- 应用状态：`~/.tdx-trend/app_state.json`
- 模拟交易状态：`~/.tdx-trend/sim_state.json`

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

## 首次使用检查清单

1. 使用 `start.bat`（Windows）或 `start.sh`（Linux/macOS）启动。
2. 确认后端健康检查可访问：
   - Windows 默认：`http://127.0.0.1:8010/health`
   - Linux/macOS `start.sh`：`http://127.0.0.1:8000/health`
3. 打开前端：`http://127.0.0.1:4173`。
4. 依次验证选股、信号、交易、复盘页面流程。

## 故障排查

- 页面打不开：
  - 确认后端运行正常（`/health` 返回 200）
  - 确认前端运行在 `4173`
  - 浏览器强制刷新（`Ctrl+F5`）
- 数据加载失败：
  - 检查设置中的 `tdx_data_path` 和行情源
  - 调用 `POST /api/system/sync-market-data` 同步行情
- 后端已启动但前端接口失败：
  - 检查后端实际端口
  - 启动前端前设置正确的 `VITE_API_PROXY_TARGET`
- 端口冲突：
  - 后端：`uvicorn app.main:app --reload --host 127.0.0.1 --port 8011`
  - 前端：`npm run dev -- --port 4174`
- 需要完全重置：
  - 停止服务
  - 清理前端缓存 `frontend/node_modules/.vite`
  - 重新执行 `start.bat` 或 `start.sh`

## 相关文档

- `docs/QUICKSTART.md`
- `docs/ARCHITECTURE.md`
- `docs/VERIFICATION.md`

# 🚀 Final Trade 使用指南

## 最简单的启动方法

### Windows 用户
双击运行 `start.bat` 文件，脚本会自动：
1. ✅ 启动后端服务
2. ✅ 验证后端运行
3. ✅ 启动前端服务
4. ✅ 自动打开浏览器

### Linux/Mac 用户
```bash
chmod +x start.sh
./start.sh
```

## 手动启动（高级用户）

### 1️⃣ 启动后端
```bash
cd backend
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

看到这个信息说明启动成功：
```
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### 2️⃣ 启动前端
```bash
cd frontend
npm run dev
```

看到这个信息说明启动成功：
```
➜  Local:   http://localhost:4173/
```

### 3️⃣ 访问应用
打开浏览器访问：**http://localhost:4173**

## 📂 项目结构

```
final-trade/
├── start.bat              # Windows 快速启动脚本 ⭐
├── start.sh               # Linux/Mac 快速启动脚本 ⭐
├── docs/                  # 文档目录
│   ├── QUICKSTART.md      # 快速启动指南
│   ├── ARCHITECTURE.md    # 架构文档
│   └── VERIFICATION.md    # 验证报告
├── backend/               # 后端服务
│   └── app/               # 应用代码
│       ├── core/          # 核心业务逻辑
│       ├── providers/     # 数据提供者
│       ├── utils/         # 工具模块
│       └── ...
└── frontend/              # 前端应用
    └── src/               # 源代码
```

## 🎯 主要功能

### 1. 股票筛选器
- 多市场选股（沪市、深市、北交所）
- 四步筛选流程
- 技术指标分析
- 趋势分类

### 2. Wyckoff 信号分析
- 自动检测累积/派发信号
- 阶段判断（吸筹A-E，派发A-E）
- 多维度评分
- 事件序列验证

### 3. 模拟交易
- T+1 交易规则
- 订单管理（买入/卖出/取消）
- 持仓跟踪
- 成交记录
- 费用计算

### 4. AI 分析
- 智能选股分析
- 主题识别
- 上涨原因推断
- 支持多个 AI 提供商

### 5. 数据复盘
- 交易统计
- 收益曲线
- 月度报告
- 回撤分析

## 🔧 配置说明

### 数据源配置
访问 http://127.0.0.1:8000/api/config 查看或修改配置：
- `tdx_data_path`: 通达信数据路径
- `market_data_source`: 数据源类型（tdx_only/akshare/tdx_with_fallback）
- `markets`: 支持的市场

### AI 配置
- `ai_providers`: AI 服务提供商配置
- `ai_timeout_sec`: 请求超时时间
- `ai_retry_count`: 重试次数

### 模拟交易配置
- `initial_capital`: 初始资金
- `commission_rate`: 手续费率
- `stamp_tax_rate`: 印花税率
- `slippage_rate`: 滑点率

## 📚 文档索引

1. **[快速启动指南](./docs/QUICKSTART.md)**
   - 详细的启动步骤
   - 常见问题解决
   - 完整重启流程

2. **[架构文档](./docs/ARCHITECTURE.md)**
   - 技术栈说明
   - 模块职责
   - 设计原则
   - 开发指南

3. **[验证报告](./docs/VERIFICATION.md)**
   - 启动验证
   - API 测试
   - 性能验证

## ❓ 常见问题

### Q: 网页打不开？
**A**: 按以下步骤检查：
1. 确认后端已启动（访问 http://127.0.0.1:8000/api/config）
2. 确认前端已启动（看到 "➜  Local: http://localhost:4173/"）
3. 清除浏览器缓存（Ctrl+Shift+Delete）
4. 尝试使用无痕模式

### Q: 数据加载失败？
**A**: 检查数据源配置：
1. 确认 `tdx_data_path` 配置正确
2. 确认通达信数据文件存在
3. 尝试同步市场数据

### Q: 端口被占用？
**A**: 更换端口启动：
```bash
# 后端
python -m uvicorn app.main:app --reload --port 8001

# 前端
npm run dev -- --port 4174
```

### Q: API 请求失败？
**A**: 检查：
1. 后端服务是否运行
2. 前端 API 配置是否正确
3. 浏览器控制台是否有错误（F12）

## 🆘 获取帮助

### 查看日志
- **后端日志**: 在运行后端的终端窗口查看
- **前端日志**: 浏览器控制台（按 F12）

### 重启服务
1. 按 Ctrl+C 停止服务
2. 重新运行启动命令或双击 `start.bat`

### 完全重置
```bash
# 停止所有服务
# 清理前端缓存
cd frontend
rm -rf node_modules/.vite
# 重新启动
cd ..
start.bat  # Windows
# 或
./start.sh # Linux/Mac
```

## 🎉 开始使用

现在你已经准备好了！运行 `start.bat`（Windows）或 `start.sh`（Linux/Mac）开始使用 Final Trade 股票分析系统！

祝投资顺利！ 📈

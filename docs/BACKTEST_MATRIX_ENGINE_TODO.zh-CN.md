# 回测矩阵引擎改造 TODO（Matrix Engine）

> 状态：Phase A/B 已落地（执行中）
> 更新时间：2026-02-21
> 目标：在不破坏旧路径的前提下，引入矩阵化信号计算，优先解决 `full_market` 回测速度。

## 1. 改造边界
- [x] 默认开关关闭，确保可回滚。
- [x] 旧路径保持完整可用。
- [ ] 任一偏差超阈值自动回退旧路径（Phase C）。

## 2. Phase A（先落地）

### A1. 新增矩阵基础模块
- [x] 新增 `backend/app/core/backtest_matrix_engine.py`
- [x] 定义 `MatrixBundle(open/high/low/close/volume/valid_mask/dates/symbols)`
- [x] 支持 `npz` 读写缓存
- [x] 缓存 key = `symbols_hash + date_range + data_version + window_set + algo_version`

### A2. 新增矩阵信号模块
- [x] 新增 `backend/app/core/backtest_signal_matrix.py`
- [x] 输出 `S1~S9`、`in_pool`、`buy_signal`、`sell_signal`、`score`（shape=(T,N)）
- [x] 缺失值/停牌安全处理（统一通过 `valid_mask`）

### A3. 接入 store（灰度起步）
- [x] `store.py` 增加开关 `TDX_TREND_BACKTEST_MATRIX_ENGINE`
- [x] Phase A：先在 `mode=full_market && pool_roll_mode=daily` 接矩阵路径
- [x] 开关关闭时 100% 走旧路径
- [x] 矩阵路径失败时可回落旧路径并记录 `notes`

### A4. 执行层改造（保留日循环）
- [x] `backtest_engine.py` 增加“消费矩阵信号切片”的入口
- [x] 避免旧逻辑中的逐股逐日快照重算
- [x] 维持旧执行语义（T+1、止损止盈、最大持仓等）

## 3. Phase B（扩展）
- [x] 扩展到 `full_market + weekly/position`
- [x] weekly 预生成刷新日 mask
- [x] position 只做矩阵切片，不重跑 rolling
- [x] 迁移 `trend_pool` 到同一矩阵信号实现

## 4. Phase C（验证与收敛）

### C1. 测试
- [x] 新增 `backend/tests/test_backtest_matrix_engine.py`
- [ ] 扩展 `backend/tests/test_backtest_api.py` 做旧/新 A/B 严格对比
- [ ] 允许极小浮点差异，保证交易语义一致

### C2. 文档
- [ ] 更新 `docs/BACKTEST_ROLLING_EVENT_STORE_TODO.zh-CN.md`
- [ ] 补充：开关、缓存目录、回滚策略、偏差阈值

## 5. 回滚策略
- [x] 开关默认关闭。
- [x] 失败自动回退旧路径并记录回退原因（`notes`）。
- [ ] 出现偏差超阈值时，自动回退旧路径并告警。

# 通达信趋势选股系统 - 需求文档

> 参考文档: 趋势票选股系统 v1.1

## 0. 文档元信息

- 文档版本: `v2.0-draft`
- 文档状态: `Draft`
- 更新日期: `2026-02-12`
- 适用范围: 全量一期，包含选股漏斗、K线图分析、AI题材分析、模拟交易、交易复盘。
- 不在范围:
  - 实盘下单与券商账户直连
  - 多用户协作与权限系统
  - 云端部署与分布式计算

---

## 1. 术语与统一记号

### 1.1 术语

| 术语 | 定义 |
|------|------|
| 活跃强势池 | 第1步筛选后得到的股票集合，来源于40日涨幅前500叠加活跃度过滤后的结果。 |
| 启动日 | 从横盘/下跌结构转向放量上行结构的首个确认交易日。 |
| A | 阶梯慢牛类型，波动低，回调浅，均线结构稳定。 |
| A_B | 慢牛段进入加速段类型，波动中等，量价共振增强。 |
| B | 脉冲型上涨，涨停驱动明显，波动高，回撤深。 |
| Unknown | 当前数据不足或信号冲突导致无法分类。 |
| 回踩 | 价格在突破后向下回撤至均线或关键突破位附近。 |
| 放量 | 当前成交量高于比较基准成交量，默认基准为5日均量。 |
| VWAP | 成交量加权均价，公式为 `sum(price * volume) / sum(volume)`。 |

### 1.2 统一记号

- 时区: `Asia/Shanghai`
- 价格精度: 统一保留2位小数
- 百分比: 文档中的 `5%` 表示数值 `0.05`
- 交易日窗口: 以有交易数据的日期序列计算，不含停牌空档日
- 股票代码格式: `市场前缀 + 6位代码`，示例 `sh600000`、`sz000001`

---

## 2. 数据契约

### 2.1 通达信本地数据契约

- 默认数据路径: `D:\new_tdx\vipdoc`（用户可配置）
- 目录结构: `{market}/{lday|minline}/`
- 支持市场: `sh`、`sz`、`bj`，以及后续新增市场
- 市场范围由用户在系统设置中勾选

### 2.2 `.day` 日线记录契约

- 单条记录长度: `32` 字节
- 字节序: 小端序
- 解析格式: `struct.unpack('<IIIIIfII', data)`
- 字段定义:

| 字段 | 类型 | 原始含义 | 归一化规则 |
|------|------|----------|------------|
| trade_date | uint | `YYYYMMDD` | 转换为 `date` |
| open_raw | uint | 开盘价*100 | `open = open_raw / 100` |
| high_raw | uint | 最高价*100 | `high = high_raw / 100` |
| low_raw | uint | 最低价*100 | `low = low_raw / 100` |
| close_raw | uint | 收盘价*100 | `close = close_raw / 100` |
| amount_raw | float | 成交额 | `amount_cny = amount_raw` |
| volume_raw | uint | 成交量原值 | `volume_shares = volume_raw * volume_lot_size` |
| reserved | uint | 保留字段 | 保留原值 |

- `volume_lot_size` 默认值: `100`，合法区间: `[1, 1000]`

### 2.3 `.lc1` / `.lc5` 分钟线记录契约

- 单条记录长度: `32` 字节
- 字节序: 小端序
- 解析格式: `struct.unpack('<HHfffffII', data)`
- 字段定义:

| 字段 | 类型 | 原始含义 | 归一化规则 |
|------|------|----------|------------|
| raw_date | ushort | 编码日期 | `year = (raw_date >> 11) + 2004`；`month = (raw_date % 2048) // 100`；`day = (raw_date % 2048) % 100` |
| raw_time | ushort | 编码时间 | `hour = raw_time // 60`；`minute = raw_time % 60` |
| open | float | 开盘价 | 保留 |
| high | float | 最高价 | 保留 |
| low | float | 最低价 | 保留 |
| close | float | 收盘价 | 保留 |
| amount_cny | float | 成交额 | 保留 |
| volume_raw | uint | 成交量原值 | `volume_shares = volume_raw * volume_lot_size` |
| reserved | uint | 保留字段 | 保留原值 |

### 2.4 本地解析异常处理

- 文件长度不能被32整除时:
  - 跳过尾部残缺字节
  - `parse_stats.trailing_bytes += n`
  - 写入结构化日志 `tdx_parse_trailing_bytes`
- 单条记录日期或时间非法时:
  - 跳过该记录
  - `parse_stats.invalid_rows += 1`
  - 写入结构化日志 `tdx_parse_invalid_row`
- 文件读取失败时:
  - 返回错误码 `TDX_FILE_IO_ERROR`
  - 当前任务标记 `degraded=true`

### 2.5 外部数据契约（多源回退）

- 资源1: `float_shares(symbol, date)`，返回流通股本
- 资源2: `sector_mapping(symbol)`，返回行业与题材映射
- 回退链:
  1. 主数据源
  2. 备数据源
  3. 本地CSV缓存

### 2.6 缓存与新鲜度

- `float_shares` 缓存TTL: `7天`
- `sector_mapping` 缓存TTL: `1天`
- 新鲜度要求:
  - 日线/分钟线: 收盘后数据可读取
  - 行业板块映射: 允许 `T+1` 更新

### 2.7 降级标识

- 任意外部依赖失败且进入回退链时，结果对象必须输出:
  - `degraded=true`
  - `degraded_reason=<错误码或原因>`

---

## 3. 功能需求

## 3.1 选股漏斗（4步，GWT）

### 3.1.1 第1步: 涨幅入口 + 活跃度过滤（全自动）

#### 规则定义

- 输入范围:
  - 全市场A股
  - 非ST
  - 上市交易日数 `> 250`
  - 市场由用户配置（沪/深/北交所）
- 计算规则:
  - 40日累计涨幅: `ret40 = close_t / close_t-40 - 1`
  - 排序后取前 `500` 只
  - 活跃度门槛（20日窗口）:
    - 日均换手率 `>= 5%`
    - 日均成交额 `>= 5e8`（人民币）
    - 日均振幅 `>= 3%`
- 输出确定化:
  - 通过数 `> 400`: 按综合分排序后截断到 `400`
  - 通过数 `< 100`: 全部保留并写告警 `POOL_TOO_SMALL`
  - 其余: 全部保留
- 综合分公式（用于 `>400` 截断）:
  - `score = 0.50 * pct_rank(ret40) + 0.20 * pct_rank(turnover20) + 0.20 * pct_rank(amount20) + 0.10 * pct_rank(amplitude20)`
  - 同分按 `symbol` 升序

#### GWT

- Given: 用户选择 `sh+sz` 市场并完成当日数据刷新。
  When: 执行第1步筛选。
  Then: 输出池数量遵循 `>400截断/ <100告警/其余全保留` 规则，且每只股票附带 `ret40/turnover20/amount20/amplitude20/score`。

- Given: 某股票缺失 `float_shares` 且回退链失败。
  When: 计算换手率。
  Then: 该股票标记 `degraded=true` 且 `degraded_reason=FLOAT_SHARES_UNAVAILABLE`，并从活跃度通过池排除。

### 3.1.2 第2步: 量化快筛 + K线图辅助（半自动）

#### 规则定义

- 严格模式（默认）:
  - `MA5 > MA10 > MA20`
  - `close > MA20`
  - 最近5日 `MA5` 未下穿 `MA10`
  - 当前价相对20日最高点回撤区间 `[5%, 25%]`
- 宽松模式:
  - `MA5 >= MA10 * 0.995`
  - `MA10 >= MA20 * 0.995`
  - `close >= MA20 * 0.98`
  - 最近5日最多1日 `MA5 < MA10`
  - 当前价相对20日最高点回撤区间 `[3%, 30%]`
- 输出字段:
  - `suggest_start_date`
  - `suggest_stage`（Early/Mid/Late）
  - `suggest_trend_class`（A/A_B/B/Unknown）
  - `confidence`（0~1）
  - `reason`（规则命中说明）
- 启动日阶段:
  - `start_gain < 30%` -> `Early`
  - `30% <= start_gain <= 80%` -> `Mid`
  - `start_gain > 80%` -> `Late`
- 人工覆盖优先级:
  - `manual > auto`
  - 覆盖后保留审计字段 `updated_by/updated_at/update_reason`

#### GWT

- Given: 股票满足严格模式全部规则。
  When: 执行第2步。
  Then: 股票进入待确认池，系统返回建议启动日、阶段、趋势类型、置信度和原因。

- Given: 股票不满足严格模式但满足宽松模式。
  When: 用户切换到宽松模式。
  Then: 股票进入待确认池，并在结果中标记 `mode=loose`。

- Given: 用户在图上手动修改 `start_date` 与 `trend_class`。
  When: 保存结果。
  Then: 后续计算全部使用手工值，自动值保留为历史字段。

### 3.1.3 第3步: 量能判断（自动 + 人工确认）

#### 评分规则（0~100）

- `score = s1 + s2 + s3 + s4 - p1 - p2 - p3`，最终截断到 `[0, 100]`
- 正向项:
  - `s1` 近20日量能斜率:
    - `vol_slope > 0` -> `25`
    - 其他 -> `0`
  - `s2` 上涨日量能/下跌日量能比值:
    - `>=1.3` -> `25`
    - `[1.1,1.3)` -> `15`
    - `<1.1` -> `5`
  - `s3` 回调缩量:
    - `pullback_vol_ratio <= 0.7` -> `25`
    - `(0.7,0.9]` -> `12`
    - `>0.9` -> `0`
  - `s4` 无天量见天价:
    - 满足 -> `25`
    - 不满足 -> `0`
- 负向项:
  - `p1` 近5日量价背离 -> `10`
  - `p2` 巨量长上影 -> `15`
  - `p3` 高位放巨量收阴/十字 -> `15`
- 标签阈值:
  - `score >= 70`: `健康`
  - `40 <= score <= 69`: `观察`
  - `score < 40`: `排除`

#### GWT

- Given: 股票满足全部正向项且未命中负向项。
  When: 执行量能评分。
  Then: 分数在 `70~100`，标签为 `健康`，并输出各子项得分明细。

- Given: 股票命中 `p2` 与 `p3`。
  When: 执行量能评分。
  Then: 分数下降至少 `30` 分，标签不高于 `观察`。

- Given: 用户将标签从 `观察` 改为 `保留`。
  When: 保存人工判断。
  Then: 后续流程使用人工标签，系统保留覆盖记录。

### 3.1.4 第4步: 题材判断（AI辅助）

#### 规则定义

- 分类结果: `发酵中`、`高潮`、`退潮`、`Unknown`
- AI输入:
  - 股票代码、所属板块、近5日行情摘要、用户配置信息源
- AI失败降级:
  - 请求超时、空结果、provider错误 -> 回退最近 `7天` 缓存
  - 无缓存 -> `Unknown`
- 输出字段:
  - `theme_stage`
  - `confidence`
  - `source_urls`
  - `analysis_summary`
  - `degraded/degraded_reason`

#### GWT

- Given: AI provider正常返回并给出高置信度结论。
  When: 执行题材判断。
  Then: 输出三态之一与来源链接集合。

- Given: AI provider超时且本地有7天内缓存。
  When: 执行题材判断。
  Then: 使用缓存结果，标记 `degraded=true` 和 `degraded_reason=AI_TIMEOUT`。

- Given: AI provider超时且本地无缓存。
  When: 执行题材判断。
  Then: 返回 `theme_stage=Unknown`，并保留人工确认入口。

## 3.2 买点信号提示（AC）

- AC-1 买点A（回踩均线买入）:
  - 收盘价位于 `MA10 * [0.98, 1.02]`
  - 当日量 `< MA5_VOL * 0.7`
  - 收盘价 `> MA20`
  - 连续回调天数 `<= 3`
- AC-2 买点B（突破新高回踩确认）:
  - 近3日存在放量突破前高，且突破日量 `>= MA5_VOL * 1.5`
  - 回踩不破突破位，回踩幅度 `< 3%`
  - 回踩日成交量 `<= 突破日成交量 * 0.8`
- AC-3 买点C（板块分歧转一致）:
  - 板块先出现分歧日，再出现一致转强日
  - 目标票在分歧日相对板块抗跌
- AC-4 冲突优先级固定 `B > A > C`。
- AC-5 同日多信号仅主信号入主列表，其他信号记录到 `secondary_signals`。
- AC-6 信号在K线图与列表同时展示，字段包含 `signal_type/trigger_date/expire_date/reason`。

## 3.3 模拟交易（GWT）

### 规则定义

- 交易标的来源: 最终待买清单
- 买入/卖出成交价:
  - 分钟线存在: `T日VWAP = sum(price*volume)/sum(volume)`
  - 分钟线缺失: `T日近似价 = (O+H+L+C)/4`
  - 近似价场景必须输出 `price_source=approx` 与 `warning=LOW_CONFIDENCE_PRICE`
- A股交易约束:
  - `T+1` 才可卖出
  - 停牌/涨停买入不可成交/跌停卖出不可成交/一字板不可成交 -> 顺延到下一交易日
  - 连续 `5` 个交易日未成交 -> 订单自动取消
- 仓位:
  - 支持分批买入和分批卖出
  - 最小交易单位 `100` 股
- 费用模型（默认）:
  - 佣金 `0.03%`，单笔最低 `5` 元
  - 印花税（卖出）`0.10%`
  - 过户费 `0.001%`
- 结果计算:
  - 每日收盘后刷新持仓市值、浮盈亏、已实现盈亏

### GWT

- Given: 当日分钟线齐全且订单满足成交条件。
  When: 提交模拟买入。
  Then: 成交价按 `T日VWAP` 写入，`price_source=vwap`。

- Given: 当日分钟线缺失且订单满足成交条件。
  When: 提交模拟买入。
  Then: 成交价按 `(O+H+L+C)/4` 写入，`price_source=approx` 且带低可信告警。

- Given: 持仓在买入当日发起卖出。
  When: 提交卖出订单。
  Then: 返回 `REJECT_T_PLUS_1_RULE`，订单不进入撮合队列。

- Given: 订单连续5个交易日因涨跌停或停牌未成交。
  When: 进入第5日收盘处理。
  Then: 订单状态变更为 `cancelled`，原因 `UNFILLED_5D`。

## 3.4 交易记录与复盘（AC）

- AC-1 记录字段:
  - `symbol`、`buy_date`、`buy_price`、`sell_date`、`sell_price`、`holding_days`、`pnl_amount`、`pnl_ratio`、`fees_total`
- AC-2 交易历史支持按时间、收益率、持仓天数筛选和排序。
- AC-3 固定统计公式:
  - 胜率: `win_rate = winning_trades / closed_trades`
  - 总收益率: `total_return = (equity_end - equity_start) / equity_start`
  - 最大回撤: `max_drawdown = max((peak_equity - current_equity) / peak_equity)`
  - 平均盈亏比: `avg_pnl_ratio = sum(pnl_ratio) / closed_trades`
- AC-4 导出交易记录为Excel，字段与系统列表一致。
- AC-5 导出选股报告为PDF，包含筛选路径、信号、交易建议、复盘统计。

## 3.5 AI集成（AC）

- AC-1 统一AI接口层支持多provider（OpenAI、通义千问、文心一言等）。
- AC-2 调用控制:
  - 单次请求超时: `10秒`
  - 重试次数: `2`
  - 退避策略: `1秒 -> 2秒`
- AC-3 错误码统一:
  - `AI_TIMEOUT`
  - `AI_HTTP_ERROR`
  - `AI_RATE_LIMIT`
  - `AI_AUTH_ERROR`
  - `AI_EMPTY_RESULT`
  - `AI_PARSE_ERROR`
- AC-4 落库字段:
  - `provider`
  - `symbol`
  - `source_urls`
  - `fetched_at`
  - `summary`
  - `conclusion`
  - `confidence`
  - `error_code`
  - `raw_response_hash`
- AC-5 API Key 明文存储路径:
  - Windows: `%USERPROFILE%\\.tdx-trend\\app.config.json`
  - 文档与UI均显示风险提示和最小权限建议

## 3.6 系统设置（AC）

- AC-1 参数必须具备默认值、合法区间、越界处理。
- AC-2 越界输入统一处理: 拒绝保存并返回 `VALIDATION_ERROR`。
- AC-3 参数清单:

| 参数 | 默认值 | 合法区间 |
|------|--------|----------|
| tdx_data_path | `D:\\new_tdx\\vipdoc` | 本地可读目录 |
| markets | `["sh","sz"]` | `sh/sz/bj` 子集 |
| return_window_days | `40` | `[20,120]` |
| top_n | `500` | `[100,2000]` |
| turnover_threshold | `5%` | `[1%,20%]` |
| amount_threshold | `5e8` | `[5e7,5e9]` |
| amplitude_threshold | `3%` | `[1%,15%]` |
| drawdown_low_strict | `5%` | `[0%,20%]` |
| drawdown_high_strict | `25%` | `[10%,40%]` |
| drawdown_low_loose | `3%` | `[0%,20%]` |
| drawdown_high_loose | `30%` | `[10%,50%]` |
| volume_lot_size | `100` | `[1,1000]` |
| initial_capital | `1000000` | `[10000,100000000]` |
| ai_provider | `openai` | provider枚举值 |
| ai_timeout_sec | `10` | `[3,60]` |
| ai_retry_count | `2` | `[0,5]` |
| api_key_path | `%USERPROFILE%\\.tdx-trend\\app.config.json` | 本地可写路径 |

---

## 4. 公共接口与类型（文档级契约）

```ts
type TrendClass = "A" | "A_B" | "B" | "Unknown";
type ThemeStage = "发酵中" | "高潮" | "退潮" | "Unknown";
type SignalType = "A" | "B" | "C";
type PriceSource = "vwap" | "approx";

interface DataProvider {
  get_float_shares(symbol: string, date: string): Promise<number>;
  get_sector_mapping(symbol: string): Promise<{ industry: string; themes: string[] }>;
  refresh(): Promise<void>;
}

interface ScreenerParams {
  markets: string[];
  return_window_days: number;
  top_n: number;
  turnover_threshold: number;
  amount_threshold: number;
  amplitude_threshold: number;
  mode: "strict" | "loose";
}

interface ScreenerResult {
  symbol: string;
  passed_step1: boolean;
  passed_step2: boolean;
  passed_step3: boolean;
  passed_step4: boolean;
  reject_reasons: string[];
  score: number;
  labels: string[];
  degraded: boolean;
  degraded_reason?: string;
}

interface TrendClassification {
  trend_class: TrendClass;
  confidence: number; // 0~1
  reason: string;
}

interface SignalResult {
  symbol: string;
  primary_signal?: SignalType;
  secondary_signals: SignalType[];
  trigger_reason: string;
  trigger_date: string;
  expire_date: string;
  priority: number;
}

interface SimTradeOrder {
  order_id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  signal_date: string;
  submit_date: string;
  status: "pending" | "filled" | "cancelled" | "rejected";
  reject_reason?: string;
}

interface SimTradeFill {
  order_id: string;
  symbol: string;
  fill_date: string;
  fill_price: number;
  price_source: PriceSource;
  fee_commission: number;
  fee_stamp_tax: number;
  fee_transfer: number;
  slippage: number;
  warning?: string;
}

interface AIAnalysisRecord {
  provider: string;
  symbol: string;
  source_urls: string[];
  fetched_at: string;
  summary: string;
  conclusion: string;
  confidence: number;
  error_code?: string;
}

interface AppConfig {
  tdx_data_path: string;
  markets: string[];
  screener: ScreenerParams;
  sla: {
    screener_p95_sec: number;
    chart_p95_sec: number;
    task_fail_rate_daily: number;
  };
  ai_provider: string;
  api_key_path: string; // 明文存储
  source_strategy: "all_web" | "user_whitelist";
}
```

---

## 5. 非功能需求（SLA）

- SLA-1 全市场 `5000+` 股票筛选耗时 `P95 <= 60秒`
- SLA-2 单票K线与指标叠加加载 `P95 <= 2秒`
- SLA-3 单日关键任务失败率 `<= 2%`
- SLA-4 关键任务支持自动重试并输出重试日志
- SLA-5 Excel导出成功率 `>= 99%`（单次1万行内）
- SLA-6 PDF导出成功率 `>= 98%`（单次200页内）

---

## 6. 测试用例与验收场景

| ID | 场景 | 前置数据 | 执行动作 | 预期输出 | 失败判据 |
|----|------|----------|----------|----------|----------|
| T-01 | `.day` 解析正确性 | 含正常与残缺记录的样本文件 | 执行解析 | 正常记录入库，残缺字节计数+日志 | 解析中断或计数缺失 |
| T-02 | `.lc1/.lc5` 时间解码 | 编码时间样本 | 执行解码 | 生成正确日期时间 | 日期或分钟越界 |
| T-03 | 第1步数量规则 | 固定样本池 | 执行第1步 | 命中 `>400`/`<100`/其他分支规则 | 输出数量不符合规则 |
| T-04 | 严格/宽松模式差异 | 同一股票集合 | 分别运行两模式 | 宽松模式结果数 >= 严格模式结果数 | 结果数关系反向 |
| T-05 | 自动识别+人工覆盖 | 含人工修正样本 | 自动识别后人工覆盖 | 后续流程使用人工值 | 仍引用自动值 |
| T-06 | 量能评分边界 | 分别构造 39/40/69/70 分样本 | 执行评分 | 标签分别为排除/观察/观察/健康 | 标签阈值错误 |
| T-07 | 买点冲突优先级 | 同日触发 A/B/C | 生成信号 | 主信号为B，其余入 secondary_signals | 主信号不是B |
| T-08 | VWAP成交 | 含分钟线交易日 | 提交订单 | 成交价按VWAP | 价格来源错误 |
| T-09 | 分钟线缺失成交 | 仅日线交易日 | 提交订单 | 成交价按OHLC均值，标记approx | 无告警或计算错误 |
| T-10 | T+1限制 | 当日买入并当日卖出 | 提交卖单 | 返回拒绝码 `REJECT_T_PLUS_1_RULE` | 卖单进入撮合 |
| T-11 | 未成交5日取消 | 连续涨停或停牌样本 | 连续撮合5日 | 订单状态 `cancelled` | 订单未取消 |
| T-12 | AI降级路径 | 模拟超时/空结果 | 执行题材分析 | 有缓存走缓存，无缓存为Unknown | 降级分支错误 |
| T-13 | 导出一致性 | 固定交易集 | 导出Excel/PDF | 导出字段与页面一致 | 字段缺失或错位 |
| T-14 | SLA监测 | 压测样本 | 运行压测脚本 | 指标满足SLA阈值 | 任一SLA越界 |

---

## 7. 风险闭环

| 风险ID | 触发条件 | 影响范围 | 缓解动作 | 阻塞级别 | 关闭标准 |
|--------|----------|----------|----------|----------|----------|
| R-01 外部数据不可用 | 主源和备源均失败 | 第1步换手率与第4步题材判断 | 启用CSV缓存、记录degraded、告警到UI | Blocker | 连续5个交易日可稳定获取或缓存命中率>=99% |
| R-02 AI抓取稳定性与合规 | 抓取站点限制、反爬、内容波动 | 题材结论稳定性与可追溯性 | 统一错误码、来源URL留痕、可切换信息源策略 | High | 30天内AI调用成功率>=98%，关键来源可追溯率100% |
| R-03 明文Key泄露 | 配置文件被误传或外泄 | AI账户安全与费用风险 | 首次配置强提示、最小权限Key、30天轮换建议 | High | 配置页已展示风险提示且用户完成确认，审计日志可查 |
| R-04 走势识别准确率不足 | 自动分类与人工判断偏差高 | 第2步效率与可信度 | 输出confidence与reason，人工覆盖优先 | Medium | 抽样200只股票后，自动分类与人工一致率>=70% |

---

## 8. 假设与取舍

### 8.1 版本假设

- 全量一期不拆版本。
- 文档中显式区分:
  - 阻塞级功能: 第1步数据完整性、模拟交易成交规则、核心导出能力
  - 可降级功能: AI题材分析、板块映射细粒度更新

### 8.2 已接受取舍

- 模拟成交口径以 `T日VWAP` 为主，分钟线缺失时使用 `OHLC` 均值近似并告警。
- AI信息获取允许全网抓取，风险由产品侧接受。
- API Key 明文存储为当前阶段取舍，配套最小权限与轮换策略。
- 外部数据采用多源回退+缓存，不依赖单一数据源。

### 8.3 固定默认值

- 40日涨幅窗口、前500初筛、活跃度阈值（换手率/成交额/振幅）保持固定默认值。
- 量能评分阈值 `70/40` 固定。
- 题材缓存回退窗口 `7天` 固定。
- 模拟交易未成交自动取消窗口 `5个交易日` 固定。


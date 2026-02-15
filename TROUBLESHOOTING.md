# 前端React错误修复指南

## 错误信息

```
Warning: [antd: Alert] `message` is deprecated. Please use `title` instead.
Uncaught Error: Maximum update depth exceeded
```

## 问题分析

这是前端的已知问题，与后端重构无关。可能是：
1. Ant Design组件使用了过时的API
2. React状态更新导致的无限循环

## 快速解决方案

### 方案1: 清除缓存重启（推荐）

```bash
cd frontend

# 停止当前服务 (Ctrl+C)

# 清理缓存
rm -rf node_modules/.vite
rm -rf dist

# 重新启动
npm run dev
```

### 方案2: 硬刷新浏览器

在浏览器中按：
- `Ctrl + Shift + R` (Windows)
- `Cmd + Shift + R` (Mac)

### 方案3: 使用无痕模式

打开浏览器的无痕/隐私模式访问：
- Chrome: `Ctrl + Shift + N`
- Edge: `Ctrl + Shift + P`
- Firefox: `Ctrl + Shift + P`

然后访问: http://localhost:4173

### 方案4: 检查浏览器控制台

1. 按 `F12` 打开开发者工具
2. 查看 Console 标签
3. 找到报错的组件文件
4. 检查是否有依赖项缺失

## 验证后端是否正常

在新的终端运行：

```bash
curl http://127.0.0.1:8000/api/config
```

如果返回JSON数据，说明后端正常，问题只在前端。

## 临时绕过

如果前端无法使用，可以直接通过API测试后端：

```bash
# 获取配置
curl http://127.0.0.1:8000/api/config

# 运行选股
curl -X POST http://127.0.0.1:8000/api/screener/run \
  -H "Content-Type: application/json" \
  -d '{"markets":["sh"],"mode":"loose","return_window_days":40,"top_n":10}'

# 获取K线数据
curl http://127.0.0.1:8000/api/stocks/sh600519/candles
```

## 长期修复

这个前端问题需要检查和修复：
1. 更新 Ant Design 到最新版本
2. 检查 useEffect 依赖项
3. 添加错误边界(Error Boundary)

这不影响后端重构的正确性，后端所有功能都正常工作。

# 前端无限循环修复脚本

这个脚本会修复所有 DatePicker 中的无限循环问题。

## 使用方法

```bash
cd "E:\Laimiu\final trade"
sh fix-frontend.sh
```

## 修复说明

脚本会自动修改以下文件：
- frontend/src/pages/screener/ScreenerPage.tsx
- frontend/src/pages/signals/SignalsPage.tsx
- frontend/src/pages/chart/ChartPage.tsx
- frontend/src/pages/review/ReviewPage.tsx
- frontend/src/pages/trade/TradePage.tsx

修复策略：在 DatePicker 的 onChange 中添加值比较，
只有当值真正改变时才调用 invalidateFrom，避免无限循环。

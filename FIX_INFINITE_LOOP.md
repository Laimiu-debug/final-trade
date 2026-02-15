# 前端无限循环修复方案

## 问题根源

在 `ScreenerPage.tsx` 中，`DatePicker` 的 `onChange` 事件直接调用了 `invalidateFrom`，这会导致：

1. 用户选择日期 → `onChange` 触发
2. `invalidateFrom` 更新状态
3. 状态更新触发重新渲染
4. 重新渲染时 `value` 属性读取 form state
5. form state 的变化再次触发 `onChange`
6. 无限循环...

## 修复方法

### 方法1: 使用 `onOk` 替代 `onChange`（推荐）

将 DatePicker 的 `onChange` 改为 `onOk`，只在用户确认选择时才触发：

```tsx
// 当前代码（有问题）
<DatePicker
  value={pickerValue}
  onChange={(next) => {
    field.onChange(next ? next.format('YYYY-MM-DD') : '')
    invalidateFrom(1)  // 这会触发无限循环
  }}
/>

// 修复后的代码
<DatePicker
  value={pickerValue}
  onChange={(next) => {
    // 只更新表单，不触发 invalidate
    field.onChange(next ? next.format('YYYY-MM-DD') : '')
  }}
  onOk={(next) => {
    // 用户确认选择时才触发 invalidate
    field.onChange(next.format('YYYY-MM-DD'))
    invalidateFrom(1)
  }}
/>
```

### 方法2: 添加值比较

在 `onChange` 中添加值比较，只有值真正改变时才触发：

```tsx
<DatePicker
  value={pickerValue}
  onChange={(next) => {
    const newValue = next ? next.format('YYYY-MM-DD') : ''
    const currentValue = field.value || ''

    // 只有值真正改变时才更新
    if (newValue !== currentValue) {
      field.onChange(newValue)
      invalidateFrom(1)
    }
  }}
/>
```

### 方法3: 使用 useCallback 优化

使用 `useCallback` 记忆化 onChange 处理函数：

```tsx
const handleDateChange = useCallback((next: any) => {
  const newValue = next ? next.format('YYYY-MM-DD') : ''
  field.onChange(newValue)
  invalidateFrom(1)
}, [field])

<DatePicker
  value={pickerValue}
  onChange={handleDateChange}
/>
```

## 完整修复代码

在 `frontend/src/pages/screener/ScreenerPage.tsx` 的第 2275-2284 行，替换为：

```tsx
<DatePicker
  allowClear
  value={pickerValue}
  format="YYYY-MM-DD"
  style={{ width: '100%' }}
  onChange={(next) => {
    const newValue = next ? next.format('YYYY-MM-DD') : ''
    if (newValue !== (field.value || '')) {
      field.onChange(newValue)
      invalidateFrom(1)
    }
  }}
/>
```

## 验证修复

应用修复后：
1. 清除浏览器缓存
2. 硬刷新页面 (Ctrl+Shift+R)
3. 尝试选择日期
4. 不应该再出现无限循环错误

## 其他受影响的组件

同样的问题可能存在于：
- `SignalsPage.tsx` 中的 DatePicker
- `ChartPage.tsx` 中的 DatePicker
- `ReviewPage.tsx` 中的 DatePicker
- `TradePage.tsx` 中的 DatePicker

需要在所有这些文件中应用相同的修复。

## 快速修复所有文件

如果你想快速修复所有文件，可以搜索：

```
onChange={.*=>.*\{[\s\S]*?invalidateFrom.*?\}
```

并替换为使用值比较的版本。

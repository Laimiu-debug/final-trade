import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { StockAnnotation } from '@/types/contracts'

interface UIState {
  selectedSymbol?: string
  stockNameMap: Record<string, string>
  annotationDrafts: Record<string, StockAnnotation>
  setSelectedSymbol: (symbol: string, name?: string) => void
  upsertDraft: (draft: StockAnnotation) => void
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      selectedSymbol: undefined,
      stockNameMap: {},
      annotationDrafts: {},
      setSelectedSymbol: (symbol, name) =>
        set((state) => ({
          selectedSymbol: symbol,
          stockNameMap:
            name && name.trim().length > 0
              ? { ...state.stockNameMap, [symbol]: name.trim() }
              : state.stockNameMap,
        })),
      upsertDraft: (draft) =>
        set((state) => ({
          annotationDrafts: {
            ...state.annotationDrafts,
            [draft.symbol]: draft,
          },
        })),
    }),
    {
      name: 'tdx-trend-ui-store',
      partialize: (state) => ({
        stockNameMap: state.stockNameMap,
        annotationDrafts: state.annotationDrafts,
      }),
    },
  ),
)

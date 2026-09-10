import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type Dispatch,
  type ReactNode,
} from 'react'
import {
  summarySSEDataSchema,
  type SummarySSEData,
} from '@/shared/schemas'

const DEFAULT_LIMIT = 10

type State = {
  summaries: SummarySSEData[]
  isLoading: boolean
  error: Error | null
}

type Action =
  | { type: 'hydrate'; summaries: SummarySSEData[] }
  | { type: 'add'; summary: SummarySSEData }
  | { type: 'error'; error: Error }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'hydrate':
      return { summaries: action.summaries, isLoading: false, error: null }
    case 'add':
      return {
        ...state,
        summaries: [action.summary, ...state.summaries],
      }
    case 'error':
      return { ...state, isLoading: false, error: action.error }
  }
}

const SummaryContext = createContext<{
  state: State
  dispatch: Dispatch<Action>
} | null>(null)

function useSummaryContext() {
  const ctx = useContext(SummaryContext)
  if (!ctx) {
    throw new Error('useSummaries must be used within SummaryProvider')
  }
  return ctx
}

export function SummaryProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    summaries: [],
    isLoading: true,
    error: null,
  })

  useEffect(() => {
    fetch(`/api/summaries?limit=${DEFAULT_LIMIT}`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch summaries')
        return res.json()
      })
      .then((data) => {
        const summaries = summarySSEDataSchema.array().parse(data)
        dispatch({ type: 'hydrate', summaries })
      })
      .catch((err) => dispatch({ type: 'error', error: err }))
  }, [])

  useEffect(() => {
    const es = new EventSource('/api/transcripts/stream')

    es.addEventListener('summary', (e) => {
      const summary = summarySSEDataSchema.parse(JSON.parse(e.data))
      dispatch({ type: 'add', summary })
    })

    es.addEventListener('error', () => {
      dispatch({ type: 'error', error: new Error('SSE connection lost') })
    })

    return () => es.close()
  }, [])

  return (
    <SummaryContext.Provider value={{ state, dispatch }}>
      {children}
    </SummaryContext.Provider>
  )
}

export function useSummaries() {
  const { state } = useSummaryContext()
  return {
    summaries: state.summaries,
    isLoading: state.isLoading,
    error: state.error,
  }
}

import {
  createContext,
  useContext,
  useEffect,
  useReducer,
  type Dispatch,
  type ReactNode,
} from 'react'
import {
  transcriptSSEDataSchema,
  type TranscriptSSEData,
} from '@/shared/schemas'
import useSWRMutation from 'swr/mutation'

const DEFAULT_LIMIT = 10

type State = {
  transcripts: TranscriptSSEData[]
  selectedIds: Set<string>
  isLoading: boolean
  error: Error | null
}

type Action =
  | { type: 'hydrate'; transcripts: TranscriptSSEData[] }
  | { type: 'add'; transcript: TranscriptSSEData }
  | { type: 'update'; id: string; correctedText: string }
  | { type: 'error'; error: Error }
  | { type: 'toggle-select'; id: string }
  | { type: 'clear-selection' }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'hydrate':
      return { ...state, transcripts: action.transcripts, isLoading: false, error: null }
    case 'add':
      return {
        ...state,
        transcripts: [action.transcript, ...state.transcripts],
      }
    case 'update':
      return {
        ...state,
        transcripts: state.transcripts.map((t) =>
          t.id === action.id
            ? { ...t, correctedText: action.correctedText }
            : t
        ),
      }
    case 'error':
      return { ...state, isLoading: false, error: action.error }
    case 'toggle-select': {
      const next = new Set(state.selectedIds)
      if (next.has(action.id)) next.delete(action.id)
      else next.add(action.id)
      return { ...state, selectedIds: next }
    }
    case 'clear-selection':
      return { ...state, selectedIds: new Set() }
  }
}

const TranscriptContext = createContext<{
  state: State
  dispatch: Dispatch<Action>
} | null>(null)

function useTranscriptContext() {
  const ctx = useContext(TranscriptContext)
  if (!ctx) {
    throw new Error('useTranscripts must be used within TranscriptProvider')
  }
  return ctx
}

export function TranscriptProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    transcripts: [],
    selectedIds: new Set<string>(),
    isLoading: true,
    error: null,
  })

  useEffect(() => {
    fetch(`/api/transcripts?limit=${DEFAULT_LIMIT}`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to fetch transcripts')
        return res.json()
      })
      .then((data) => {
        const transcripts = transcriptSSEDataSchema.array().parse(data)
        dispatch({ type: 'hydrate', transcripts })
      })
      .catch((err) => dispatch({ type: 'error', error: err }))
  }, [])

  useEffect(() => {
    const es = new EventSource('/api/transcripts/stream')

    es.addEventListener('transcript', (e) => {
      const transcript = transcriptSSEDataSchema.parse(JSON.parse(e.data))
      dispatch({ type: 'add', transcript })
    })

    es.addEventListener('error', () => {
      dispatch({ type: 'error', error: new Error('SSE connection lost') })
    })

    return () => es.close()
  }, [])

  return (
    <TranscriptContext.Provider value={{ state, dispatch }}>
      {children}
    </TranscriptContext.Provider>
  )
}

export function useTranscripts() {
  const { state } = useTranscriptContext()
  return {
    transcripts: state.transcripts,
    isLoading: state.isLoading,
    error: state.error,
  }
}

export function useTranscriptSelection() {
  const { state, dispatch } = useTranscriptContext()
  return {
    selectedIds: state.selectedIds,
    toggleSelect: (id: string) => dispatch({ type: 'toggle-select', id }),
    clearSelection: () => dispatch({ type: 'clear-selection' }),
  }
}

export function useUpdateTranscript(id: string) {
  const { dispatch } = useTranscriptContext()

  return useSWRMutation(
    `/api/transcripts/${id}`,
    async (url, { arg }: { arg: { correctedText: string } }) => {
      const res = await fetch(url, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(arg),
      })
      if (!res.ok) throw new Error('Failed to save correction')
      return arg
    },
    {
      onSuccess: (data) => {
        dispatch({ type: 'update', id, correctedText: data.correctedText })
      },
    },
  )
}

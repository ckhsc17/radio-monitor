import { useCallback, useRef, useState } from 'react'

type ReportState = {
  content: string
  isGenerating: boolean
  error: string | null
}

export function useReport() {
  const [state, setState] = useState<ReportState>({
    content: '',
    isGenerating: false,
    error: null,
  })
  const abortRef = useRef<AbortController | null>(null)

  const generateReport = useCallback(async (transcriptIds: string[]) => {
    setState({ content: '', isGenerating: true, error: null })

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch('/api/generate-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcriptIds }),
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let accumulated = ''
      let buffer = ''
      let currentEvent = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (currentEvent === 'token') {
              accumulated += data
              setState((prev) => ({ ...prev, content: accumulated }))
            } else if (currentEvent === 'error') {
              setState((prev) => ({ ...prev, error: data }))
            }
          }
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : String(err),
      }))
    } finally {
      setState((prev) => ({ ...prev, isGenerating: false }))
      abortRef.current = null
    }
  }, [])

  const stopGenerating = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const clearReport = useCallback(() => {
    setState({ content: '', isGenerating: false, error: null })
  }, [])

  return { ...state, generateReport, stopGenerating, clearReport }
}

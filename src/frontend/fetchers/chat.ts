import { useCallback, useRef, useState } from 'react'
import type { ChatMessage } from '@/shared/schemas'

type ChatState = {
  messages: ChatMessage[]
  isStreaming: boolean
  error: string | null
}

export function useChat() {
  const [state, setState] = useState<ChatState>({
    messages: [],
    isStreaming: false,
    error: null,
  })
  const abortRef = useRef<AbortController | null>(null)
  const messagesRef = useRef<ChatMessage[]>([])

  const sendMessage = useCallback(async (userMessage: string) => {
    const userMsg: ChatMessage = { role: 'user', content: userMessage }
    const allMessages = [...messagesRef.current, userMsg]
    messagesRef.current = allMessages

    setState((prev) => ({
      messages: [...prev.messages, userMsg],
      isStreaming: true,
      error: null,
    }))

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: allMessages }),
        signal: controller.signal,
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''
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
              assistantContent += data
              setState((prev) => {
                const msgs = [...prev.messages]
                const lastMsg = msgs[msgs.length - 1]
                if (lastMsg?.role === 'assistant') {
                  msgs[msgs.length - 1] = { ...lastMsg, content: assistantContent }
                } else {
                  msgs.push({ role: 'assistant', content: assistantContent })
                }
                return { ...prev, messages: msgs }
              })
            } else if (currentEvent === 'error') {
              setState((prev) => ({ ...prev, error: data }))
            }
          }
        }
      }

      messagesRef.current = [...allMessages, { role: 'assistant', content: assistantContent }]
    } catch (err) {
      if (controller.signal.aborted) return
      setState((prev) => ({
        ...prev,
        error: err instanceof Error ? err.message : String(err),
      }))
    } finally {
      setState((prev) => ({ ...prev, isStreaming: false }))
      abortRef.current = null
    }
  }, [])

  const stopStreaming = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const clearMessages = useCallback(() => {
    messagesRef.current = []
    setState({ messages: [], isStreaming: false, error: null })
  }, [])

  return { ...state, sendMessage, stopStreaming, clearMessages }
}

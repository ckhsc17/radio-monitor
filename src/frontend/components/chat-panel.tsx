import { useState, useRef, useEffect } from 'react'
import { useChat } from '@/frontend/fetchers/chat'
import { Send, Square, Trash2 } from 'lucide-react'
import { MarkdownContent } from './markdown'

export function ChatPanel() {
  const { messages, isStreaming, error, sendMessage, stopStreaming, clearMessages } = useChat()
  const [input, setInput] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || isStreaming) return
    setInput('')
    sendMessage(trimmed)
  }

  return (
    <div className='flex flex-col h-full'>
      <div className='flex-1 overflow-y-auto px-4 py-2 space-y-3'>
        {messages.length === 0 && (
          <p className='text-gray-400 text-sm text-center mt-8'>
            輸入問題以查詢無線電通訊紀錄
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'bg-brand-blue text-white whitespace-pre-wrap'
                  : 'bg-gray-100 text-brand-text'
              }`}
            >
              {msg.role === 'assistant' ? <MarkdownContent content={msg.content} /> : msg.content}
            </div>
          </div>
        ))}
        {isStreaming && messages[messages.length - 1]?.role !== 'assistant' && (
          <div className='flex justify-start'>
            <div className='bg-gray-100 rounded-lg px-3 py-2 text-sm text-gray-400'>
              思考中...
            </div>
          </div>
        )}
        {error && <p className='text-red-500 text-xs text-center'>{error}</p>}
        <div ref={messagesEndRef} />
      </div>

      <div className='border-t border-brand-border px-4 py-2 shrink-0'>
        <form onSubmit={handleSubmit} className='flex items-center gap-2'>
          <input
            type='text'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder='輸入問題...'
            disabled={isStreaming}
            className='flex-1 border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:border-brand-blue'
          />
          {isStreaming ? (
            <button type='button' onClick={stopStreaming} className='text-red-500 hover:text-red-700'>
              <Square size={20} />
            </button>
          ) : (
            <button
              type='submit'
              disabled={!input.trim()}
              className='text-brand-blue hover:text-brand-blue-300 disabled:text-gray-300'
            >
              <Send size={20} />
            </button>
          )}
          {messages.length > 0 && !isStreaming && (
            <button type='button' onClick={clearMessages} className='text-gray-400 hover:text-gray-600'>
              <Trash2 size={16} />
            </button>
          )}
        </form>
      </div>
    </div>
  )
}

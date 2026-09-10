import Anthropic from '@anthropic-ai/sdk'
import { enqueueOllamaTask } from './ollama-client'

export type ChatMessage = { role: 'system' | 'user' | 'assistant'; content: string }

export type ChatStreamCallback = (token: string) => void

export interface ChatProvider {
  streamChat(
    messages: ChatMessage[],
    onToken: ChatStreamCallback,
    signal?: AbortSignal,
  ): Promise<void>
}

const CHAT_OLLAMA_OPTIONS = {
  temperature: 0.7,
  top_p: 0.9,
  num_ctx: 2048,
}

class OllamaChatProvider implements ChatProvider {
  constructor(
    private host: string,
    private model: string,
  ) {}

  async streamChat(messages: ChatMessage[], onToken: ChatStreamCallback, signal?: AbortSignal) {
    await enqueueOllamaTask(async () => {
      const res = await fetch(`${this.host.replace(/\/+$/, '')}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.model,
          messages,
          stream: true,
          options: CHAT_OLLAMA_OPTIONS,
        }),
        signal,
      })

      if (!res.ok) {
        const detail = await res.text().catch(() => '')
        throw new Error(`Ollama HTTP ${res.status}: ${detail.slice(0, 500)}`)
      }

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.trim()) continue
          const chunk = JSON.parse(line)
          if (chunk.message?.content) {
            onToken(chunk.message.content)
          }
        }
      }
    })
  }
}

class ClaudeChatProvider implements ChatProvider {
  private client: Anthropic

  constructor(
    apiKey: string,
    private model: string,
  ) {
    this.client = new Anthropic({ apiKey })
  }

  async streamChat(messages: ChatMessage[], onToken: ChatStreamCallback, signal?: AbortSignal) {
    const systemMessage = messages.find((m) => m.role === 'system')?.content ?? ''
    const chatMessages = messages
      .filter((m) => m.role !== 'system')
      .map((m) => ({ role: m.role as 'user' | 'assistant', content: m.content }))

    const stream = this.client.messages.stream(
      {
        model: this.model,
        max_tokens: 2048,
        system: systemMessage,
        messages: chatMessages,
      },
      { signal },
    )

    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        onToken(event.delta.text)
      }
    }
  }
}

type ChatEnv = {
  CHAT_PROVIDER: 'ollama' | 'claude'
  CHAT_MODEL?: string
  OLLAMA_HOST: string
  OLLAMA_MODEL: string
  ANTHROPIC_API_KEY?: string
}

export function createChatProvider(chatEnv: ChatEnv): ChatProvider {
  if (chatEnv.CHAT_PROVIDER === 'claude') {
    if (!chatEnv.ANTHROPIC_API_KEY) {
      throw new Error('ANTHROPIC_API_KEY is required when CHAT_PROVIDER=claude')
    }
    return new ClaudeChatProvider(
      chatEnv.ANTHROPIC_API_KEY,
      chatEnv.CHAT_MODEL ?? 'claude-sonnet-4-20250514',
    )
  }
  return new OllamaChatProvider(
    chatEnv.OLLAMA_HOST,
    chatEnv.CHAT_MODEL ?? chatEnv.OLLAMA_MODEL,
  )
}

import { ollamaOutputSchema } from '@/shared/schemas'

export type OllamaConfig = {
  host: string
  model: string
  systemPrompt: string
}

export type OllamaSummaryResult = {
  rawTranscript: string
  polished: string
  reasoning: string
  summary: string
}

const USER_INSTRUCTION_TEXT =
  'The following is a raw ASR transcript of an EMS radio segment. ' +
  'It may contain homophone errors, dropped syllables, or garbage tokens; use context and domain knowledge to infer likely ' +
  'intended terms, but never invent clinical facts not supported by the transcript. ' +
  'Respond with only the JSON object (keys raw_transcript, polished, reasoning, summary) as specified in the system message.\n\n' +
  'Raw transcript:\n'

const OLLAMA_OPTIONS = {
  temperature: 1.0,
  top_p: 0.95,
  top_k: 64,
  num_ctx: 2048,
}

function stripMarkdownFences(text: string) {
  let s = text.trim()
  if (s.startsWith('```json')) s = s.slice(7)
  else if (s.startsWith('```')) s = s.slice(3)
  if (s.endsWith('```')) s = s.slice(0, -3)
  return s.trim()
}

async function callOllama(config: OllamaConfig, transcript: string): Promise<OllamaSummaryResult> {
  const url = `${config.host.replace(/\/+$/, '')}/api/chat`
  const body = {
    model: config.model,
    messages: [
      { role: 'system', content: config.systemPrompt },
      { role: 'user', content: USER_INSTRUCTION_TEXT + transcript.trim() },
    ],
    stream: false,
    options: OLLAMA_OPTIONS,
  }

  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(120_000),
  })

  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`Ollama HTTP ${response.status}: ${detail.slice(0, 500)}`)
  }

  const data = await response.json()
  const content: string = (data.message?.content ?? '').trim()

  if (!content) {
    throw new Error('Ollama returned empty content')
  }

  const cleaned = stripMarkdownFences(content)

  let json: unknown
  try {
    json = JSON.parse(cleaned)
  } catch {
    console.warn('Ollama returned non-JSON content, using raw content as summary')
    return {
      rawTranscript: transcript,
      polished: '',
      reasoning: '',
      summary: content,
    }
  }

  const parsed = ollamaOutputSchema.safeParse(json)

  if (!parsed.success) {
    console.warn('Ollama output did not match schema, using raw content as summary')
    return {
      rawTranscript: transcript,
      polished: '',
      reasoning: '',
      summary: content,
    }
  }

  return {
    rawTranscript: parsed.data.raw_transcript,
    polished: parsed.data.polished,
    reasoning: parsed.data.reasoning,
    summary: parsed.data.summary,
  }
}

let pending = Promise.resolve<unknown>()

export function enqueueOllamaTask<T>(fn: () => Promise<T>): Promise<T> {
  const next = pending.then(() => fn())
  pending = next.catch(() => {})
  return next
}

export function summarizeTranscript(config: OllamaConfig, transcript: string): Promise<OllamaSummaryResult> {
  return enqueueOllamaTask(() => callOllama(config, transcript))
}

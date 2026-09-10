import { mkdirSync } from 'node:fs'
import { join } from 'path'
import { serve } from 'bun'
import { Hono } from 'hono'
import { streamSSE } from 'hono/streaming'
import { migrate } from 'drizzle-orm/bun-sqlite/migrator'
import { AUDIOS_DIR } from './contstants.ts'
import { env } from './env.ts'
import index from './frontend/index.html'
import { startTranscription } from './transcribe.ts'
import type { TranscriptSSEData, SummarySSEData } from './shared/schemas.ts'
import { chatRequestSchema, reportRequestSchema } from './shared/schemas.ts'
import { zValidator } from '@hono/zod-validator'
import z from 'zod'
import { db } from './db.ts'
import { transcriptsTable, summariesTable } from './db/schema.ts'
import { desc, eq } from 'drizzle-orm'
import { getAsrProvider } from './lib/asr-resolve.ts'
import { summarizeTranscript, type OllamaConfig } from './lib/ollama-client.ts'
import { createChatProvider, type ChatMessage } from './lib/chat-provider.ts'

mkdirSync(AUDIOS_DIR, { recursive: true })

await migrate(db, { migrationsFolder: join(import.meta.dir, '..', 'drizzle') })

const ollamaConfig: OllamaConfig | null = env.OLLAMA_ENABLED
  ? {
      host: env.OLLAMA_HOST,
      model: env.OLLAMA_MODEL,
      systemPrompt: await Bun.file(join(import.meta.dir, '..', 'scripts', 'prompts', 'radio_system.txt')).text(),
    }
  : null

if (ollamaConfig) {
  console.log(`Ollama enabled: model=${ollamaConfig.model} host=${ollamaConfig.host}`)
}

const chatSystemPrompt = await Bun.file(join(import.meta.dir, '..', 'scripts', 'prompts', 'chat_system.txt')).text()
const reportSystemPrompt = await Bun.file(join(import.meta.dir, '..', 'scripts', 'prompts', 'report_system.txt')).text()
const chatProvider = createChatProvider(env)

const app = new Hono().basePath('/api')

type SSEListener = {
  sendTranscript: (data: TranscriptSSEData) => void
  sendSummary: (data: SummarySSEData) => void
}

const listeners = new Set<SSEListener>()

app.get(
  '/transcripts',
  zValidator(
    'query',
    z.object({
      page: z.coerce.number().int().positive().default(1),
      limit: z.coerce.number().int().positive().max(100).default(10),
    }),
  ),
  (c) => {
    const { page, limit } = c.req.valid('query')
    const offset = (page - 1) * limit

    const rows = db
      .select()
      .from(transcriptsTable)
      .orderBy(desc(transcriptsTable.time))
      .limit(limit)
      .offset(offset)
      .all()

    const transcripts: TranscriptSSEData[] = rows.map((row) => ({
      id: row.id,
      text: row.text,
      time: row.time ? row.time.getTime() : 0,
      correctedText: row.correctedText ?? null,
    }))

    return c.json(transcripts)
  },
)

app.patch(
  '/transcripts/:id',
  zValidator('param', z.object({ id: z.string() })),
  zValidator('json', z.object({ correctedText: z.string() })),
  (c) => {
    const { id } = c.req.valid('param')
    const { correctedText } = c.req.valid('json')

    const row = db
      .select({ id: transcriptsTable.id })
      .from(transcriptsTable)
      .where(eq(transcriptsTable.id, id))
      .get()

    if (!row) {
      return c.json({ error: 'Transcript not found' }, 404)
    }

    db.update(transcriptsTable)
      .set({ correctedText })
      .where(eq(transcriptsTable.id, id))
      .run()

    return c.json({ id, correctedText })
  },
)

app.get(
  '/summaries',
  zValidator(
    'query',
    z.object({
      page: z.coerce.number().int().positive().default(1),
      limit: z.coerce.number().int().positive().max(100).default(10),
    }),
  ),
  (c) => {
    const { page, limit } = c.req.valid('query')
    const offset = (page - 1) * limit

    const rows = db
      .select()
      .from(summariesTable)
      .orderBy(desc(summariesTable.time))
      .limit(limit)
      .offset(offset)
      .all()

    const summaries: SummarySSEData[] = rows.map((row) => ({
      id: row.id,
      transcriptId: row.transcriptId,
      time: row.time ? row.time.getTime() : 0,
      rawTranscript: row.rawTranscript ?? null,
      polished: row.polished ?? null,
      reasoning: row.reasoning ?? null,
      summary: row.summary ?? null,
    }))

    return c.json(summaries)
  },
)

app.get('/transcripts/stream', (c) => {
  return streamSSE(c, async (stream) => {
    const listener: SSEListener = {
      sendTranscript: (data) => {
        stream.writeSSE({
          data: JSON.stringify(data),
          event: 'transcript',
        })
      },
      sendSummary: (data) => {
        stream.writeSSE({
          data: JSON.stringify(data),
          event: 'summary',
        })
      },
    }
    listeners.add(listener)
    stream.onAbort(() => {
      listeners.delete(listener)
    })
    await new Promise(() => {})
  })
})

function getChatContext() {
  const recentTranscripts = db
    .select({ text: transcriptsTable.text, correctedText: transcriptsTable.correctedText, time: transcriptsTable.time })
    .from(transcriptsTable)
    .orderBy(desc(transcriptsTable.time))
    .limit(10)
    .all()

  const recentSummaries = db
    .select({ polished: summariesTable.polished, summary: summariesTable.summary, time: summariesTable.time })
    .from(summariesTable)
    .orderBy(desc(summariesTable.time))
    .limit(5)
    .all()

  let context = '## 最近的無線電轉錄紀錄\n\n'
  for (const t of recentTranscripts.reverse()) {
    const time = t.time ? t.time.toLocaleTimeString() : '?'
    context += `[${time}] ${t.correctedText ?? t.text}\n`
  }

  if (recentSummaries.length) {
    context += '\n## AI 摘要\n\n'
    for (const s of recentSummaries.reverse()) {
      const time = s.time ? s.time.toLocaleTimeString() : '?'
      if (s.polished) context += `[${time}] ${s.polished}\n`
      if (s.summary) context += `  摘要: ${s.summary}\n`
    }
  }

  return context
}

app.post(
  '/chat',
  zValidator('json', chatRequestSchema),
  (c) => {
    const { messages } = c.req.valid('json')

    return streamSSE(c, async (stream) => {
      const context = getChatContext()
      const systemMessage: ChatMessage = {
        role: 'system',
        content: chatSystemPrompt.trim() + '\n\n---\n\n' + context,
      }

      const fullMessages = [systemMessage, ...messages]

      const abortController = new AbortController()
      stream.onAbort(() => abortController.abort())

      try {
        await chatProvider.streamChat(
          fullMessages,
          (token) => {
            stream.writeSSE({ data: token, event: 'token' })
          },
          abortController.signal,
        )
        stream.writeSSE({ data: '', event: 'done' })
      } catch (err) {
        if (abortController.signal.aborted) return
        stream.writeSSE({ data: String(err), event: 'error' })
      }
    })
  },
)

app.post(
  '/generate-report',
  zValidator('json', reportRequestSchema),
  (c) => {
    const { transcriptIds } = c.req.valid('json')

    const transcripts = transcriptIds.flatMap((id) => {
      const row = db.select().from(transcriptsTable).where(eq(transcriptsTable.id, id)).get()
      return row ? [row] : []
    })

    if (transcripts.length === 0) {
      return c.json({ error: 'No transcripts found' }, 404)
    }

    const summaries = transcriptIds.flatMap((id) => {
      const row = db.select().from(summariesTable).where(eq(summariesTable.transcriptId, id)).get()
      return row ? [row] : []
    })

    let context = '## 選取的無線電通報紀錄\n\n'
    for (const t of transcripts) {
      const time = t.time ? t.time.toLocaleTimeString() : '?'
      context += `[${time}] ${t.correctedText ?? t.text}\n`
    }

    if (summaries.length) {
      context += '\n## 對應的 AI 摘要\n\n'
      for (const s of summaries) {
        if (s.polished) context += `${s.polished}\n`
        if (s.summary) context += `摘要: ${s.summary}\n`
        context += '\n'
      }
    }

    return streamSSE(c, async (stream) => {
      const systemMessage: ChatMessage = {
        role: 'system',
        content: reportSystemPrompt.trim() + '\n\n---\n\n' + context,
      }

      const fullMessages: ChatMessage[] = [
        systemMessage,
        { role: 'user', content: '請根據以上通報紀錄，生成一份緊急救護紀錄表草稿。' },
      ]

      const abortController = new AbortController()
      stream.onAbort(() => abortController.abort())

      try {
        await chatProvider.streamChat(
          fullMessages,
          (token) => {
            stream.writeSSE({ data: token, event: 'token' })
          },
          abortController.signal,
        )
        stream.writeSSE({ data: '', event: 'done' })
      } catch (err) {
        if (abortController.signal.aborted) return
        stream.writeSSE({ data: String(err), event: 'error' })
      }
    })
  },
)

app.get(
  '/transcripts/:id/audio',
  zValidator(
    'param',
    z.object({
      id: z.string(),
    }),
  ),
  async (c) => {
    const { id } = c.req.valid('param')
    const filePath = join(AUDIOS_DIR, `${id}.wav`)
    const file = Bun.file(filePath)

    const isFileExists = await file.exists()

    if (!isFileExists) {
      return c.json({ error: 'Audio not found' }, 404)
    }

    return new Response(file, {
      headers: { 'Content-Type': 'audio/wav' },
    })
  },
)

const server = serve({
  idleTimeout: 0,

  routes: {
    '/*': index,
    '/api/*': app.fetch,
  },

  development: env.NODE_ENV !== 'production' && {
    hmr: true,
    console: true,
  },
})

async function getContext() {
  const parts: string[] = []
  if (env.ASR_SCENARIO_PROMPT) parts.push(env.ASR_SCENARIO_PROMPT)
  const rows = db
    .select({ text: transcriptsTable.text, correctedText: transcriptsTable.correctedText })
    .from(transcriptsTable)
    .orderBy(desc(transcriptsTable.time))
    .limit(env.ASR_CONTEXT_LIMIT)
    .all()
  const recent = rows.map((r) => (r.correctedText ?? r.text).trim()).filter(Boolean)
  if (recent.length) parts.push(recent.join('。'))
  return parts.join('\n\n')
}

startTranscription(({ id, text }) => {
  const time = new Date(Number(id))

  db.insert(transcriptsTable).values({ id, text, time }).run()

  const transcriptData: TranscriptSSEData = {
    id,
    text,
    time: time.getTime(),
    correctedText: null,
  }
  for (const listener of listeners) listener.sendTranscript(transcriptData)

  if (ollamaConfig) {
    summarizeTranscript(ollamaConfig, text)
      .then((result) => {
        const summaryTime = new Date()

        db.insert(summariesTable).values({
          id,
          transcriptId: id,
          time: summaryTime,
          rawTranscript: result.rawTranscript,
          polished: result.polished,
          reasoning: result.reasoning,
          summary: result.summary,
        }).run()

        const summaryData: SummarySSEData = {
          id,
          transcriptId: id,
          time: summaryTime.getTime(),
          rawTranscript: result.rawTranscript,
          polished: result.polished,
          reasoning: result.reasoning,
          summary: result.summary,
        }
        for (const listener of listeners) listener.sendSummary(summaryData)

        console.log(`Summary generated for transcript ${id}`)
      })
      .catch((err) => {
        console.error(`Ollama summary failed for transcript ${id}:`, err)
      })
  }
}, getContext, getAsrProvider())

console.log(`Server running at ${server.url}`)

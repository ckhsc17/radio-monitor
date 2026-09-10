import z from 'zod'

export const transcriptSSEDataSchema = z.object({
  id: z.string(),
  text: z.string(),
  time: z.number(),
  correctedText: z.string().nullable(),
})

export type TranscriptSSEData = z.infer<typeof transcriptSSEDataSchema>

export const summarySSEDataSchema = z.object({
  id: z.string(),
  transcriptId: z.string(),
  time: z.number(),
  rawTranscript: z.string().nullable(),
  polished: z.string().nullable(),
  reasoning: z.string().nullable(),
  summary: z.string().nullable(),
})

export type SummarySSEData = z.infer<typeof summarySSEDataSchema>

export const chatMessageSchema = z.object({
  role: z.enum(['user', 'assistant']),
  content: z.string(),
})

export type ChatMessage = z.infer<typeof chatMessageSchema>

export const chatRequestSchema = z.object({
  messages: z.array(chatMessageSchema).min(1),
})

export const reportRequestSchema = z.object({
  transcriptIds: z.array(z.string()).min(1),
})

export const ollamaOutputSchema = z.object({
  raw_transcript: z.string(),
  polished: z.string(),
  reasoning: z.string(),
  summary: z.string(),
})

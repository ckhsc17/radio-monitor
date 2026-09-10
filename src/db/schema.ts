import { int, sqliteTable, text } from 'drizzle-orm/sqlite-core'

export const transcriptsTable = sqliteTable('transcripts_table', {
  id: text().primaryKey(),
  time: int({ mode: 'timestamp' }),
  text: text().notNull(),
  correctedText: text('corrected_text'),
})

export const summariesTable = sqliteTable('summaries_table', {
  id: text().primaryKey(),
  transcriptId: text('transcript_id').notNull(),
  time: int({ mode: 'timestamp' }),
  rawTranscript: text('raw_transcript'),
  polished: text(),
  reasoning: text(),
  summary: text(),
})

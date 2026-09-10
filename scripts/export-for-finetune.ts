import { mkdirSync, existsSync } from 'node:fs'
import { join } from 'node:path'
import { db } from '../src/db.ts'
import { transcriptsTable } from '../src/db/schema.ts'
import { and, isNotNull, ne } from 'drizzle-orm'

const AUDIOS_DIR = join(import.meta.dir, '..', 'data', 'audios')
const OUT_DIR = join(import.meta.dir, '..', 'data', 'finetune')
const MANIFEST = 'manifest.jsonl'

const rows = db
  .select({ id: transcriptsTable.id, correctedText: transcriptsTable.correctedText })
  .from(transcriptsTable)
  .where(and(isNotNull(transcriptsTable.correctedText), ne(transcriptsTable.correctedText, '')))
  .all()

mkdirSync(OUT_DIR, { recursive: true })

const lines: string[] = []
for (const row of rows) {
  const audioPath = join(AUDIOS_DIR, `${row.id}.wav`)
  if (!existsSync(audioPath)) continue
  const text = (row.correctedText ?? '').trim()
  if (!text) continue
  lines.push(JSON.stringify({ audio_path: audioPath, text }))
}

const outPath = join(OUT_DIR, MANIFEST)
await Bun.write(outPath, lines.join('\n') + (lines.length ? '\n' : ''))
console.log(`Wrote ${lines.length} entries to ${outPath}`)

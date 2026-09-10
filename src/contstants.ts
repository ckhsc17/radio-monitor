import { join } from 'path'

export const WHISPER_API_URL = 'http://127.0.0.1:8080/inference'

export const AUDIOS_DIR = join(import.meta.dir, '..', 'data', 'audios')

import { env } from './env.ts'

export const preprocessorConfig = {
  SQUELCH_THRESHOLD: env.SQUELCH_THRESHOLD,
  SILENCE_DURATION: 1200,
  SAMPLE_RATE: 16000,
  METER_CHUNK_BYTES: 3200, // 100ms at 16kHz mono s16le
  PRE_ROLL_CHUNKS: 5, // 500ms of audio kept before squelch triggers
}

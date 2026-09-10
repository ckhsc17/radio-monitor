import { createEnv } from '@t3-oss/env-core'
import { z } from 'zod'

export const env = createEnv({
  server: {
    NODE_ENV: z.enum(['development', 'production']).default('development'),
    AUDIO_FILE: z.string().optional(),
    MICROPHONE_ID: z.string().default('0'),
    LOG_LEVEL: z.enum(['ERROR', 'INFO', 'DEBUG']).default('INFO'),
    ASR_PROVIDER: z.enum(['whisper', 'voxtral', 'firered']).default('whisper'),
    ASR_SCENARIO_PROMPT: z.string().optional(),
    ASR_CONTEXT_LIMIT: z.coerce.number().int().positive().max(20).default(5),
    VOXTRAL_API_URL: z.string().url().optional(),
    FIRERED_ASR_API_URL: z.string().url().optional(),
    SQUELCH_THRESHOLD: z.coerce.number().min(0).max(1).default(0.1),
    OLLAMA_HOST: z.string().url().default('http://127.0.0.1:11434'),
    OLLAMA_MODEL: z.string().default('qwen2.5:7b-instruct-q4_K_M'),
    OLLAMA_ENABLED: z
      .enum(['true', 'false', '1', '0'])
      .default('false')
      .transform((v) => v === 'true' || v === '1'),
    CHAT_PROVIDER: z.enum(['ollama', 'claude']).default('ollama'),
    CHAT_MODEL: z.string().optional(),
    ANTHROPIC_API_KEY: z.string().optional(),
  },
  runtimeEnv: process.env,
  emptyStringAsUndefined: true,
})

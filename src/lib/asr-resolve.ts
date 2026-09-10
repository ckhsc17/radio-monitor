import { env } from '@/env'
import type { AsrProvider } from './asr-provider.ts'
import { createWhisperProvider } from './whisper-provider.ts'
import { createVoxtralProvider } from './voxtral-provider.ts'
import { createFireRedProvider } from './firered-provider.ts'

export function getAsrProvider(): AsrProvider {
  switch (env.ASR_PROVIDER) {
    case 'whisper':
      return createWhisperProvider()
    case 'voxtral': {
      const url = env.VOXTRAL_API_URL
      if (!url) throw new Error('VOXTRAL_API_URL is required when ASR_PROVIDER=voxtral')
      return createVoxtralProvider(url)
    }
    case 'firered': {
      const url = env.FIRERED_ASR_API_URL
      if (!url) throw new Error('FIRERED_ASR_API_URL is required when ASR_PROVIDER=firered')
      return createFireRedProvider(url)
    }
    default:
      return createWhisperProvider()
  }
}

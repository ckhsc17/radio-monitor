import { join } from 'path'
import { preprocessorConfig, WHISPER_API_URL } from '@/contstants'
import { AUDIOS_DIR } from '@/contstants'
import { createFormData } from '@/utils/form-data'
import type { AsrProvider, TranscribeInput } from './asr-provider.ts'

export function createWhisperProvider(): AsrProvider {
  return {
    async transcribe({ id, wavBuffer, context }: TranscribeInput) {
      await Bun.write(join(AUDIOS_DIR, `${id}.wav`), wavBuffer)

      const formData = createFormData({
        response_format: 'json',
        language: 'zh',
        prompt: context ?? '',
        temperature: 0,
        temperature_inc: 0.1,
        entropy_thold: 2.0,
        logprob_thold: -0.5,
        best_of: 5,
        suppress_nst: 'true',
        vad: 'true',
      })
      formData.append('file', new Blob([new Uint8Array(wavBuffer)]), 'audio.wav')

      try {
        const response = await fetch(WHISPER_API_URL, {
          method: 'POST',
          body: formData,
        })

        if (!response.ok) throw new Error(`API Error: ${response.statusText}`)

        const result = await response.json()
        const text = (result.text as string)?.trim() ?? ''
        console.log(`API Response: ${text}`)
        return text
      } catch (error) {
        console.error('Transcription Failed:', error)
        return ''
      }
    },
  }
}

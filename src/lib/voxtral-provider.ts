import type { AsrProvider, TranscribeInput } from './asr-provider.ts'

export function createVoxtralProvider(apiUrl: string): AsrProvider {
  return {
    async transcribe({ wavBuffer, context }: TranscribeInput) {
      const formData = new FormData()
      formData.append('file', new Blob([wavBuffer]), 'audio.wav')
      if (context) formData.append('context', context)

      try {
        const response = await fetch(apiUrl, { method: 'POST', body: formData })
        const raw = await response.text()
        let result: { text?: string; error?: string }
        try {
          result = JSON.parse(raw) as { text?: string; error?: string }
        } catch {
          result = {}
        }
        if (!response.ok) {
          const msg =
            result.error?.trim() ||
            raw.slice(0, 200).trim() ||
            response.statusText
          throw new Error(`Voxtral API Error: ${response.status} ${msg}`)
        }
        return (result.text ?? '').trim()
      } catch (error) {
        console.error('Voxtral transcription failed:', error)
        return ''
      }
    },
  }
}

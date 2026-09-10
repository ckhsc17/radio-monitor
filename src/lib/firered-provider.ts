import type { AsrProvider, TranscribeInput } from './asr-provider.ts'

export function createFireRedProvider(apiUrl: string): AsrProvider {
  return {
    async transcribe({ wavBuffer, context }: TranscribeInput) {
      const formData = new FormData()
      formData.append('file', new Blob([wavBuffer]), 'audio.wav')
      if (context) formData.append('context', context)

      try {
        const response = await fetch(apiUrl, { method: 'POST', body: formData })
        if (!response.ok) throw new Error(`FireRedASR API Error: ${response.statusText}`)
        const result = (await response.json()) as { text?: string }
        return (result.text ?? '').trim()
      } catch (error) {
        console.error('FireRedASR transcription failed:', error)
        return ''
      }
    },
  }
}

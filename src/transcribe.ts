import { spawn } from 'bun'
import { env } from './env.ts'
import { ffmpegStreamArgs } from './lib/ffmpeg.ts'
import { preprocessorConfig } from './contstants.ts'
import { createWavHeader } from './utils/wav.ts'
import { calculateRMS } from './utils/audio.ts'
import type { AsrProvider } from './lib/asr-provider.ts'

export type OnTranscriptProps = { text: string; id: string }
export type OnTranscript = (props: OnTranscriptProps) => void

export function startTranscription(
  onTranscript: OnTranscript,
  getContext: () => Promise<string>,
  asrProvider: AsrProvider,
) {
  const { METER_CHUNK_BYTES, PRE_ROLL_CHUNKS } = preprocessorConfig

  let audioBuffer: Uint8Array[] = []
  let isRecording = false
  let silenceStart: number | null = null
  let pendingBytes = new Uint8Array(0)
  const preRoll: Uint8Array[] = []

  const ffmpegProc = spawn(
    ffmpegStreamArgs({ audioFilePath: env.AUDIO_FILE }),
    {
      stdout: 'pipe',
      stderr: env.LOG_LEVEL === 'DEBUG' ? 'inherit' : 'ignore',
    },
  )

  async function handleMeterChunk(chunk: Uint8Array) {
    const rms = calculateRMS({ chunk })

    if (rms > preprocessorConfig.SQUELCH_THRESHOLD) {
      if (!isRecording) {
        console.log('Rx Start... (Signal Detected)')
        isRecording = true
        audioBuffer = [...preRoll]
        preRoll.length = 0
      }
      silenceStart = null
      audioBuffer.push(chunk)
    } else if (isRecording) {
      audioBuffer.push(chunk)

      if (!silenceStart) silenceStart = Date.now()

      if (Date.now() - silenceStart > preprocessorConfig.SILENCE_DURATION) {
        console.log('Rx End. Processing...')
        await finishTransmission()
        isRecording = false
        silenceStart = null
      }
    } else {
      preRoll.push(chunk)
      if (preRoll.length > PRE_ROLL_CHUNKS) {
        preRoll.shift()
      }
    }
  }

  async function finishTransmission() {
    const id = String(Date.now())
    const totalLength = audioBuffer.reduce((acc, chunk) => acc + chunk.length, 0)
    const combinedBuffer = new Uint8Array(totalLength)
    let offset = 0
    for (const chunk of audioBuffer) {
      combinedBuffer.set(chunk, offset)
      offset += chunk.length
    }
    const wavHeader = createWavHeader(totalLength, preprocessorConfig.SAMPLE_RATE)
    const wavBuffer = new Uint8Array(wavHeader.length + combinedBuffer.length)
    wavBuffer.set(wavHeader, 0)
    wavBuffer.set(combinedBuffer, wavHeader.length)

    const context = await getContext()
    const text = await asrProvider.transcribe({ id, wavBuffer, context })
    onTranscript({ id, text })
  }

  async function runAudioLoop() {
    const reader = ffmpegProc.stdout.getReader()

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const combined = new Uint8Array(pendingBytes.length + value.length)
        combined.set(pendingBytes, 0)
        combined.set(value, pendingBytes.length)

        let offset = 0
        while (offset + METER_CHUNK_BYTES <= combined.length) {
          await handleMeterChunk(combined.slice(offset, offset + METER_CHUNK_BYTES))
          offset += METER_CHUNK_BYTES
        }
        pendingBytes = combined.slice(offset)
      }

      if (isRecording && pendingBytes.length >= 2) {
        audioBuffer.push(pendingBytes)
      }

      if (isRecording && audioBuffer.length > 0) {
        console.log('Stream ended. Flushing remaining audio...')
        await finishTransmission()
      }
    } catch (error) {
      console.error('FFmpeg stream error:', error)
    }
  }

  runAudioLoop()
}

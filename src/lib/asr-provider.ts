export type TranscribeInput = {
  id: string
  wavBuffer: Uint8Array
  context?: string
}

export type AsrProvider = {
  transcribe(input: TranscribeInput): Promise<string>
}

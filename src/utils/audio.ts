const INT16_MAX_VALUE = 2 ** 15

export function calculateRMS({ chunk }: { chunk: Uint8Array }) {
  const dataView = new DataView(
    chunk.buffer,
    chunk.byteOffset,
    chunk.byteLength,
  )

  const sampleCount = chunk.length / 2 // Each sample is 2 bytes

  let sumSquares = 0
  for (let i = 0; i < sampleCount; i++) {
    // Normalize sample amplitude (Int16) to between -1 and 1
    const sample = dataView.getInt16(i * 2, true) / INT16_MAX_VALUE

    sumSquares += sample * sample
  }

  // RMS (Root Mean Square) takes square root of average squares by definition
  const rms = Math.sqrt(sumSquares / sampleCount)

  return rms
}

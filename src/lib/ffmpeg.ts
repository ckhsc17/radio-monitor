import { preprocessorConfig } from '@/contstants'
import { env } from '@/env'
import ffmpegPath from 'ffmpeg-static'

export function ffmpegStreamArgs(props?: { audioFilePath?: string }) {
  if (!ffmpegPath) {
    throw new Error('FFMPEG not found.')
  }

  const inputArgs = props?.audioFilePath
    ? ['-re', '-i', props?.audioFilePath]
    : ['-f', 'avfoundation', '-i', `:${env.MICROPHONE_ID}`]

  const filters = [
    'highpass=f=300',
    'equalizer=f=630:width_type=h:w=15:g=-80',
    'equalizer=f=950:width_type=h:w=15:g=-80',
    'dynaudnorm=p=0.95:m=100:s=5',
  ]

  return [
    ffmpegPath,
    ...inputArgs,
    '-ac',
    '1',
    '-ar',
    String(preprocessorConfig.SAMPLE_RATE),
    '-af',
    filters.join(','),
    '-f',
    's16le',
    'pipe:1',
  ]
}

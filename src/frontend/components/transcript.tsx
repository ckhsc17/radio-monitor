import { useEffect, useRef, useState } from 'react'
import type { TranscriptSSEData } from '@/shared/schemas'
import { useUpdateTranscript, useTranscriptSelection } from '@/frontend/fetchers/transcripts'
import { useAudioPlayer } from 'react-use-audio-player'
import { CirclePlay, CirclePause, Pencil, Check, X } from 'lucide-react'

export function Transcript({
  transcript: { id, time, text, correctedText },
}: {
  transcript: TranscriptSSEData
}) {
  const { isPlaying, isLoading, togglePlayPause, duration, getPosition, seek } =
    useAudioPlayer(`/api/transcripts/${id}/audio`, {
      autoplay: false,
      html5: true,
      format: 'wav',
    })

  const { trigger, isMutating } = useUpdateTranscript(id)
  const { selectedIds, toggleSelect } = useTranscriptSelection()
  const isSelected = selectedIds.has(id)

  const frameRef = useRef<number>(0)
  const [position, setPosition] = useState(0)
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!isPlaying) return

    function animate() {
      setPosition(getPosition())
      frameRef.current = requestAnimationFrame(animate)
    }

    frameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameRef.current)
  }, [isPlaying, getPosition])

  useEffect(() => {
    if (isEditing) inputRef.current?.focus()
  }, [isEditing])

  async function saveCorrection() {
    const trimmed = editValue.trim()
    if (!trimmed || trimmed === text) {
      setIsEditing(false)
      setEditValue('')
      return
    }

    await trigger({ correctedText: trimmed })
    setIsEditing(false)
  }

  return (
    <div className='px-4 space-y-1'>
      <div className={`flex w-full items-start justify-center my-2 py-1 group ${isSelected ? 'bg-blue-50' : 'hover:bg-gray-200'}`}>
        <input
          type='checkbox'
          checked={isSelected}
          onChange={() => toggleSelect(id)}
          className='mt-1.5 mr-2 shrink-0 accent-brand-blue cursor-pointer'
        />
        <p className='w-25 text-gray-400 text-xs pt-1'>
          {new Date(time).toLocaleTimeString()}
        </p>

        <div className='w-full'>
          {isEditing ? (
            <div className='flex items-center gap-1'>
              <input
                ref={inputRef}
                type='text'
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') saveCorrection()
                  if (e.key === 'Escape') {
                    setIsEditing(false)
                    setEditValue('')
                  }
                }}
                disabled={isMutating}
                className='w-full border border-gray-300 rounded px-2 py-0.5 text-black focus:outline-none focus:border-brand-blue'
              />
              <button
                onClick={() => saveCorrection()}
                disabled={isMutating}
                className='text-green-600 hover:text-green-800'
              >
                <Check size={16} />
              </button>
              <button
                onClick={() => {
                  setIsEditing(false)
                  setEditValue('')
                }}
                disabled={isMutating}
                className='text-red-500 hover:text-red-700'
              >
                <X size={16} />
              </button>
            </div>
          ) : (
            <>
              {correctedText ? (
                <>
                  <p className='text-black'>{correctedText}</p>
                  <p className='text-gray-400 text-xs line-through'>{text}</p>
                </>
              ) : (
                <p className='text-black'>{text}</p>
              )}
            </>
          )}
        </div>

        {!isEditing && (
          <div className='flex items-center gap-1'>
            <button
              onClick={() => {
                setEditValue(correctedText ?? text)
                setIsEditing(true)
              }}
              className='text-gray-400 hover:text-brand-text opacity-0 group-hover:opacity-100 transition-opacity'
            >
              <Pencil size={16} />
            </button>
            <button
              onClick={() => togglePlayPause()}
              className='text-brand-text text-xs'
              disabled={isLoading}
            >
              {isPlaying ? <CirclePause /> : <CirclePlay />}
            </button>
          </div>
        )}
      </div>
      {isPlaying && (
        <input
          type='range'
          min={0}
          max={duration}
          step={0.01}
          value={position}
          onChange={(e) => seek(parseFloat(e.target.value))}
          className='w-full h-1 accent-brand-blue cursor-pointer'
        />
      )}
    </div>
  )
}

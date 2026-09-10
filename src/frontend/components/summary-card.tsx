import { useState } from 'react'
import type { SummarySSEData } from '@/shared/schemas'
import { ChevronDown, ChevronUp } from 'lucide-react'

export function SummaryCard({ summary }: { summary: SummarySSEData }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className='px-4 py-2 border-b border-b-brand-border'>
      <div className='flex items-start gap-2'>
        <p className='w-20 shrink-0 text-gray-400 text-xs pt-1'>
          {new Date(summary.time).toLocaleTimeString()}
        </p>
        <div className='w-full space-y-1'>
          {summary.polished && (
            <p className='text-black text-sm'>{summary.polished}</p>
          )}
          {summary.summary && (
            <p className='text-brand-blue text-sm font-medium'>{summary.summary}</p>
          )}
          {summary.reasoning && (
            <>
              <button
                onClick={() => setExpanded(!expanded)}
                className='flex items-center gap-1 text-gray-400 text-xs hover:text-gray-600'
              >
                {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                推論筆記
              </button>
              {expanded && (
                <p className='text-gray-500 text-xs bg-gray-50 rounded p-2'>
                  {summary.reasoning}
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

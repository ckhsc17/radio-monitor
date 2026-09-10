import { useTranscriptSelection } from '@/frontend/fetchers/transcripts'
import { useReport } from '@/frontend/fetchers/report'
import { FileText, Square, Copy, Check, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { MarkdownContent } from './markdown'

export function ReportPanel() {
  const { selectedIds, clearSelection } = useTranscriptSelection()
  const { content, isGenerating, error, generateReport, stopGenerating, clearReport } = useReport()
  const [copied, setCopied] = useState(false)

  function handleGenerate() {
    if (selectedIds.size === 0 || isGenerating) return
    generateReport(Array.from(selectedIds))
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleClear() {
    clearReport()
    clearSelection()
  }

  return (
    <div className='flex flex-col h-full'>
      <div className='flex items-center gap-2 px-4 py-2 shrink-0 border-b border-brand-border'>
        {isGenerating ? (
          <button
            onClick={stopGenerating}
            className='flex items-center gap-1.5 px-3 py-1 rounded text-sm text-red-600 border border-red-300 hover:bg-red-50'
          >
            <Square size={14} />
            停止
          </button>
        ) : (
          <button
            onClick={handleGenerate}
            disabled={selectedIds.size === 0}
            className='flex items-center gap-1.5 px-3 py-1 rounded text-sm text-white bg-brand-blue hover:bg-brand-blue-300 disabled:bg-gray-300 disabled:cursor-not-allowed'
          >
            <FileText size={14} />
            生成報告
          </button>
        )}
        <span className='text-xs text-gray-400'>
          {selectedIds.size > 0 ? `已選 ${selectedIds.size} 筆紀錄` : '請在左上方勾選通報紀錄'}
        </span>
        {content && !isGenerating && (
          <div className='ml-auto flex items-center gap-1'>
            <button onClick={handleCopy} className='text-gray-400 hover:text-gray-600' title='複製'>
              {copied ? <Check size={16} className='text-green-600' /> : <Copy size={16} />}
            </button>
            <button onClick={handleClear} className='text-gray-400 hover:text-gray-600' title='清除'>
              <Trash2 size={16} />
            </button>
          </div>
        )}
      </div>

      <div className='flex-1 overflow-y-auto px-4 py-2'>
        {!content && !isGenerating && !error && (
          <p className='text-gray-400 text-sm text-center mt-8'>
            勾選通報紀錄後點擊「生成報告」
          </p>
        )}
        {content && <MarkdownContent content={content} />}
        {isGenerating && !content && (
          <p className='text-gray-400 text-sm text-center mt-8'>生成中...</p>
        )}
        {error && <p className='text-red-500 text-xs text-center mt-4'>{error}</p>}
      </div>
    </div>
  )
}

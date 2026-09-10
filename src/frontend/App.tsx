import { Group, Separator } from 'react-resizable-panels'
import { Panel } from './components/panels/panel'
import { TranscriptProvider, useTranscripts } from './fetchers/transcripts'
import { SummaryProvider, useSummaries } from './fetchers/summaries'
import './index.css'
import { Transcript } from './components/transcript'
import { SummaryCard } from './components/summary-card'
import { ChatPanel } from './components/chat-panel'
import { ReportPanel } from './components/report-panel'

function TranscriptList() {
  const { transcripts } = useTranscripts()

  return (
    <>
      {transcripts.map((transcript) => (
        <Transcript transcript={transcript} key={transcript.id} />
      ))}
    </>
  )
}

function SummaryList() {
  const { summaries, isLoading } = useSummaries()

  if (isLoading) {
    return <p className='px-4 text-gray-400 text-sm'>載入中...</p>
  }

  if (summaries.length === 0) {
    return <p className='px-4 text-gray-400 text-sm'>尚無摘要</p>
  }

  return (
    <>
      {summaries.map((summary) => (
        <SummaryCard summary={summary} key={summary.id} />
      ))}
    </>
  )
}

export function App() {
  return (
    <TranscriptProvider>
      <SummaryProvider>
        <div className='h-screen max-h-screen flex flex-col w-full'>
          <header className='flex items-center justify-start gap-3 text-white bg-brand-blue w-full px-4 py-3 h-12.5'>
            <img
              src='https://cdn.forward.org.tw/assets/logo-white.png'
              className='h-full'
            />
            <h1 className='text-xl font-semibold'>無線電監聽工具</h1>
          </header>
          <div className='flex h-[calc(100%-50px)] w-full flex-col text-brand-text'>
            <Group orientation='horizontal'>
              <Panel>
                <Group orientation='vertical'>
                  <Panel>
                    <div className='w-full border-b border-b-brand-border py-2 mb-2 sticky top-0 bg-brand-bg px-4'>
                      <h2 className='text-lg font-semibold'>轉錄紀錄</h2>
                    </div>
                    <TranscriptList />
                  </Panel>
                  <Separator className='bg-brand-border h-px' />
                  <Panel>
                    <div className='flex flex-col h-full'>
                      <div className='w-full border-b border-b-brand-border py-2 mb-2 shrink-0 bg-brand-bg px-4'>
                        <h2 className='text-lg font-semibold'>救護紀錄表</h2>
                      </div>
                      <div className='flex-1 min-h-0'>
                        <ReportPanel />
                      </div>
                    </div>
                  </Panel>
                </Group>
              </Panel>
              <Separator className='bg-brand-border w-px' />
              <Panel>
                <Group orientation='vertical'>
                  <Panel>
                    <div className='w-full border-b border-b-brand-border py-2 mb-2 sticky top-0 bg-brand-bg px-4'>
                      <h2 className='text-lg font-semibold'>AI 摘要</h2>
                    </div>
                    <SummaryList />
                  </Panel>
                  <Separator className='bg-brand-border h-px' />
                  <Panel>
                    <div className='flex flex-col h-full'>
                      <div className='w-full border-b border-b-brand-border py-2 mb-2 shrink-0 bg-brand-bg px-4'>
                        <h2 className='text-lg font-semibold'>AI 聊天</h2>
                      </div>
                      <div className='flex-1 min-h-0'>
                        <ChatPanel />
                      </div>
                    </div>
                  </Panel>
                </Group>
              </Panel>
            </Group>
          </div>
        </div>
      </SummaryProvider>
    </TranscriptProvider>
  )
}

import type { PropsWithChildren } from 'react'
import { Panel as RawPanel } from 'react-resizable-panels'

export function Panel({ children }: PropsWithChildren) {
  return <RawPanel className='overflow-scroll relative'>{children}</RawPanel>
}

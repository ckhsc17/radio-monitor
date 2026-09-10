 Plan: 整合 Ollama 摘要到 Bun Server

 Context

 radio-monitor 的 Bun server 目前只做 STT（ffmpeg → VAD → Whisper → SQLite → SSE → 前端），摘要功能只存在於獨立的 Python CLI (gemma4_pipeline.py)，沒有整合進即時 pipeline。前端的「AI 摘要」面板是空殼。

 目標：STT 完成後立即推轉錄到前端，同時在背景呼叫 Ollama 產生結構化摘要（raw_transcript / polished / reasoning / summary），完成後透過 SSE 補推到前端的摘要面板。

 實作步驟

 Phase 1: Backend

 1. 重命名 system prompt
 - scripts/prompts/gemma_radio_system.txt → scripts/prompts/radio_system.txt
 - 更新 scripts/gemma4_pipeline.py:46 的 DEFAULT_PROMPT_PATH

 2. 新增 env vars (src/env.ts)
 - OLLAMA_HOST (default http://127.0.0.1:11434)
 - OLLAMA_MODEL (default qwen2.5:7b-instruct-q4_K_M)
 - OLLAMA_ENABLED (default false，opt-in)

 3. 新增 summaries DB table (src/db/schema.ts)
 summariesTable: id (PK, 同 transcript ID), transcriptId (FK), time,
                 rawTranscript, polished, reasoning, summary
 然後 bun run db:generate 產生 migration。

 4. 新增 Zod schemas (src/shared/schemas.ts)
 - summarySSEDataSchema — 前端接收用
 - ollamaOutputSchema — 解析 Ollama JSON 回應用

 5. 建立 Ollama client (新檔 src/lib/ollama-client.ts)
 - summarizeTranscript(config, transcript) → POST /api/chat
 - 參數對齊 Python 版：temperature: 1.0, top_p: 0.95, top_k: 64, num_ctx: 2048
 - USER_INSTRUCTION_TEXT 從 Python 版搬過來
 - JSON 解析加 sanitizer（strip markdown fences）
 - 序列佇列避免同時跑多個推論（M1 Pro 16GB 記憶體考量）

 6. 接線 (src/index.ts)
 - 啟動時讀取 scripts/prompts/radio_system.txt 快取
 - 重構 SSE listener 為 { sendTranscript, sendSummary } 支援兩種事件
 - startTranscription callback 裡：先推 transcript，再 fire-and-forget 呼叫 Ollama → 存 DB → 推 summary SSE
 - 新增 GET /api/summaries REST endpoint（前端 hydration 用）

 Phase 2: Frontend

 7. Summary state management (新檔 src/frontend/fetchers/summaries.tsx)
 - SummaryProvider + useSummaries hook
 - useReducer with hydrate / add / error actions
 - 監聽同一個 /api/transcripts/stream 的 'summary' event

 8. Summary 元件
 - 新檔 src/frontend/components/summary-card.tsx — 顯示 polished + summary，可展開 reasoning
 - 新檔 src/frontend/components/summary-list.tsx — 列表容器

 9. 接上 App.tsx — 「AI 摘要」面板裡放 <SummaryProvider><SummaryList /></SummaryProvider>

 Phase 3: 測試

 10. 驗證流程
 - OLLAMA_ENABLED=false：確認 app 跟之前一樣正常運作
 - OLLAMA_ENABLED=true AUDIO_FILE=./docs/test.mp3 bun run app:dev：
   - 前端應先收到轉錄文字
   - 數秒後右側摘要面板收到結構化摘要
 - OLLAMA_ENABLED=false 不跑 Ollama 時確認不會 crash

 異動檔案

 ┌──────────────────────────────────────────┬────────────────────────────────────────────────────────┐
 │                   檔案                   │                          動作                          │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ scripts/prompts/gemma_radio_system.txt   │ 重命名為 radio_system.txt                              │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ scripts/gemma4_pipeline.py               │ 修改 prompt path                                       │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/env.ts                               │ 新增 3 env vars                                        │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/db/schema.ts                         │ 新增 summariesTable                                    │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/shared/schemas.ts                    │ 新增 2 schemas                                         │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/lib/ollama-client.ts                 │ 新建 — Ollama HTTP client                              │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/index.ts                             │ 重構 SSE listener + 接 Ollama pipeline + REST endpoint │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/frontend/fetchers/summaries.tsx      │ 新建 — state management                                │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/frontend/components/summary-card.tsx │ 新建 — 摘要卡片                                        │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/frontend/components/summary-list.tsx │ 新建 — 摘要列表                                        │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ src/frontend/App.tsx                     │ 接上 SummaryProvider + SummaryList                     │
 ├──────────────────────────────────────────┼────────────────────────────────────────────────────────┤
 │ .env.example                             │ 新增 Ollama env vars                                   │
 └──────────────────────────────────────────┴────────────────────────────────────────────────────────┘
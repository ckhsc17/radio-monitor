import { db } from '@/db'
import { migrate } from 'drizzle-orm/bun-sqlite/migrator'
import { mkdir } from 'node:fs/promises'

await mkdir('./data', { recursive: true })
migrate(db, { migrationsFolder: './drizzle' })

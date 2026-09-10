import { drizzle } from 'drizzle-orm/bun-sqlite'
import * as schema from './db/schema'
import { Database } from 'bun:sqlite'

const sqlite = new Database('data/db.sqlite3', { create: true })
export const db = drizzle(sqlite, { schema })

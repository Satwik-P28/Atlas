/**
 * The schema version a certified browser journey must see.
 *
 * Read from the migration chain itself rather than pinned as a literal: a new migration
 * legitimately moves the head, and a journey that hardcodes the old number fails for a
 * reason that has nothing to do with the interface it is certifying.
 */
import { readFileSync } from 'node:fs'

const source = readFileSync(
  new URL('../../src/atlas/storage/migrations.py', import.meta.url),
  'utf8',
)

const versions = [...source.matchAll(/Migration\(\s*version=(\d+)/g)].map((match) => Number(match[1]))

if (versions.length === 0) {
  throw new Error('could not read the migration chain from src/atlas/storage/migrations.py')
}

export const LATEST_SCHEMA_VERSION = Math.max(...versions)

import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

/** A fresh browser-test database before every run (backend/scripts/e2e_database.py; only zk_e2e* can be dropped). */
export default function globalSetup() {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const repo = path.resolve(here, '..', '..')
  const python = process.env.ZK_E2E_PYTHON
    ?? path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python')
  execFileSync(python, [path.join(repo, 'backend', 'scripts', 'e2e_database.py')], { stdio: 'inherit' })
}

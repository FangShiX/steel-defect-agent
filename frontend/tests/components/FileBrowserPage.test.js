import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/views/FileBrowserPage.vue'), 'utf8')

describe('FileBrowserPage default-model feedback', () => {
  it('clears stale bulk failure feedback before switching the default model', () => {
    expect(source).toContain('function clearBulkFeedback()')
    expect(source).toContain('async function setDefaultModel(model) { clearBulkFeedback();')
  })

  it('exposes dataset upload in the embedded training view', () => {
    expect(source).toContain('v-if="embedded"')
    expect(source).toContain('accept=".zip"')
    expect(source).toContain(':on-change="uploadDataset"')
    expect(source).toContain('uploadTrainingDataset(file.raw)')
  })
})

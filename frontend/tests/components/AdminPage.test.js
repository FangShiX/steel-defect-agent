import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const source = readFileSync(resolve(process.cwd(), 'src/views/AdminPage.vue'), 'utf8')

describe('AdminPage knowledge-base management', () => {
  it('exposes the real document management actions', () => {
    expect(source).toContain('uploadKnowledgeDocumentApi')
    expect(source).toContain('getKnowledgeDocumentChunksApi')
    expect(source).toContain('downloadKnowledgeDocumentApi')
    expect(source).toContain('deleteKnowledgeDocumentApi')
    expect(source).toContain('accept=".txt,.md,.pdf,.docx"')
    expect(source).toContain('v-model="chunksVisible"')
  })

  it('uploads system documents through the existing knowledge API contract', () => {
    expect(source).toContain('knowledgeIsSystem.value')
    expect(source).toContain('uploadKnowledgeDocumentApi(knowledgeTitle.value.trim(), file.raw, knowledgeIsSystem.value)')
    expect(source).toContain("await loadKnowledgeDocuments()")
  })
})

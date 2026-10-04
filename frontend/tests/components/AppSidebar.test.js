import { readFileSync } from 'fs'
import { resolve } from 'path'
import { describe, expect, it } from 'vitest'

const sidebar = readFileSync(
  resolve(process.cwd(), 'src/components/layout/AppSidebar.vue'),
  'utf8',
)

describe('AppSidebar user menu', () => {
  it('opens the settings modal from the explicit user menu entry', () => {
    expect(sidebar).toContain("handleMenuCommand('settings')")
    expect(sidebar).toContain("if (command === 'settings')")
    expect(sidebar).toContain('settingsVisible.value = true')
    expect(sidebar).toContain('<SettingsModal v-model="settingsVisible" @closed="restoreSettingsFocus" />')
  })
})

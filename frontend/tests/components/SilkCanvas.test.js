import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

vi.mock('three', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    WebGLRenderer: class {
      constructor() {
        throw new Error('WebGL unavailable')
      }
    },
  }
})

import SilkCanvas from '@/components/SilkCanvas.vue'

describe('SilkCanvas', () => {
  it('keeps a static background when WebGL initialization fails', () => {
    const wrapper = mount(SilkCanvas)

    expect(wrapper.classes()).toContain('silk-canvas')
    expect(wrapper.find('canvas').exists()).toBe(false)

    wrapper.unmount()
  })
})

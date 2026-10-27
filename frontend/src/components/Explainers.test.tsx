import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { EXPLAINERS } from './Explainers'

describe('category explainers', () => {
  it('each explainer is 300-500 words', () => {
    for (const e of EXPLAINERS) {
      const text = renderToStaticMarkup(<>{e.body}</>).replace(/<[^>]+>/g, ' ')
      const words = text.trim().split(/\s+/).length
      expect(words, e.title).toBeGreaterThanOrEqual(300)
      expect(words, e.title).toBeLessThanOrEqual(500)
    }
  })
})

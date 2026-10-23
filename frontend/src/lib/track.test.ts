import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { BATCH_SIZE, flush, resetTracking, track, TRACK_URL } from './track'

type Sent = { sessionId: string; events: { name: string; props: Record<string, unknown> }[] }

describe('track', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    resetTracking()
    fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 202 })))
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    resetTracking()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const sent = (i = 0) => JSON.parse(fetchMock.mock.calls[i][1].body as string) as Sent

  it('batches events and sends them after a short pause', () => {
    track('onboarding_step_viewed', { step: 'Basics', position: 1 })
    track('filter_applied', { filter: 'tier' })
    expect(fetchMock).not.toHaveBeenCalled()
    vi.advanceTimersByTime(2500)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe(TRACK_URL)
    const body = sent()
    expect(body.events).toEqual([{ name: 'onboarding_step_viewed', props: { step: 'basics', position: 1 } },
      { name: 'filter_applied', props: { filter: 'tier' } }])
    expect(body.sessionId).toMatch(/^[A-Za-z0-9_-]{8,64}$/)
  })

  it('keeps one visit id across batches and sends at once when a batch is full', () => {
    for (let i = 0; i < BATCH_SIZE; i++) track('compare_opened')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    track('quick_view_opened')
    flush()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(sent(0).events).toHaveLength(BATCH_SIZE)
    expect(sent(1).sessionId).toBe(sent(0).sessionId)
  })

  it('drops properties the server would not keep', () => {
    track('request_step_viewed', { step: 'Scope of work', position: -1, ...({ email: 'a@b.c' } as object) })
    flush()
    expect(sent().events[0].props).toEqual({ step: 'scope-of-work' })
  })

  it('uses sendBeacon when the page is hidden', () => {
    const beacon = vi.fn(() => true)
    vi.stubGlobal('navigator', { ...navigator, sendBeacon: beacon })
    track('request_abandoned', { step: 'budget' })
    flush(true)
    expect(beacon).toHaveBeenCalledTimes(1)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('never throws, even when sending fails', () => {
    fetchMock.mockImplementation(() => { throw new Error('offline') })
    expect(() => { track('service_card_opened'); flush() }).not.toThrow()
    fetchMock.mockImplementation(() => Promise.reject(new Error('offline')))
    expect(() => { track('service_card_opened'); flush() }).not.toThrow()
  })
})

import { afterEach, describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ReactElement, ReactNode, FormEvent } from 'react'
import { StepUpModal } from './ui'

const mocks = vi.hoisted(() => ({ stepUp: vi.fn(), portal: vi.fn() }))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ stepUp: mocks.stepUp, accept: vi.fn() }) }))
vi.mock('react-dom', () => ({ createPortal: (children: ReactNode, container: unknown) => {
  mocks.portal(children, container)
  return children
} }))

afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals() })

function renderConfirmation(onDone: () => void) {
  const body = {}
  vi.stubGlobal('document', { body })
  const html = renderToStaticMarkup(<StepUpModal open onDone={onDone} onCancel={() => {}} />)
  const dialog = mocks.portal.mock.calls[0][0] as ReactElement<{ children: ReactElement<{ onSubmit: (event: FormEvent) => Promise<void> }> }>
  return { html, body, submit: dialog.props.children.props.onSubmit }
}

describe('step-up confirmation inside a sensitive action form', () => {
  it('uses a body portal and prevents the code submission from also submitting the parent review', async () => {
    const onDone = vi.fn()
    mocks.stepUp.mockResolvedValueOnce(undefined)
    const { html, body, submit } = renderConfirmation(onDone)
    const preventDefault = vi.fn()
    const stopPropagation = vi.fn()
    await submit({ preventDefault, stopPropagation } as unknown as FormEvent)
    expect(mocks.portal.mock.calls[0][1]).toBe(body)
    expect(preventDefault).toHaveBeenCalledOnce()
    expect(stopPropagation).toHaveBeenCalledOnce()
    expect(mocks.stepUp).toHaveBeenCalledOnce()
    expect(onDone).toHaveBeenCalledOnce()
    expect(mocks.stepUp.mock.invocationCallOrder[0]).toBeLessThan(onDone.mock.invocationCallOrder[0])
    expect(html).toContain('not sent by email or SMS')
  })

  it('does not retry the sensitive action if authentication fails', async () => {
    mocks.stepUp.mockRejectedValueOnce(new Error('Invalid code'))
    const onDone = vi.fn()
    const { submit } = renderConfirmation(onDone)
    await submit({ preventDefault: vi.fn(), stopPropagation: vi.fn() } as unknown as FormEvent)
    expect(onDone).not.toHaveBeenCalled()
  })
})

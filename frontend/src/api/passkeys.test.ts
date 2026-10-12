import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from './client'
import { passkeyApi } from './passkeys'

vi.mock('./client', () => ({ api: vi.fn() }))
const request = vi.mocked(api)
class Attestation {
  clientDataJSON = Uint8Array.from([1, 2]).buffer
  attestationObject = Uint8Array.from([3, 4]).buffer
  getTransports() { return ['internal'] }
}
beforeEach(() => { vi.resetAllMocks(); vi.stubGlobal('AuthenticatorAttestationResponse', Attestation) })
afterEach(() => vi.unstubAllGlobals())

describe('browser passkey ceremonies', () => {
  it('converts server options to buffers and posts actual attestation bytes', async () => {
    const create = vi.fn().mockResolvedValue({ id: 'a2V5', rawId: Uint8Array.from([107, 101, 121]).buffer,
      type: 'public-key', response: new Attestation() })
    vi.stubGlobal('navigator', { credentials: { create } })
    request.mockResolvedValueOnce({ challengeId: 'registration', publicKey: { challenge: 'AQI',
      user: { id: 'AwQ', name: 'user@example.com', displayName: 'User' }, excludeCredentials: [{ id: 'BQY', type: 'public-key' }] } })
      .mockResolvedValueOnce({ registered: true })
    await passkeyApi.register('Laptop')
    const options = create.mock.calls[0][0].publicKey
    expect([...new Uint8Array(options.challenge)]).toEqual([1, 2])
    expect([...new Uint8Array(options.user.id)]).toEqual([3, 4])
    expect([...new Uint8Array(options.excludeCredentials[0].id)]).toEqual([5, 6])
    expect(request.mock.calls[1]).toEqual(['/v1/me/passkeys', { method: 'POST', body: {
      challengeId: 'registration', label: 'Laptop', credential: { id: 'a2V5', rawId: 'a2V5', type: 'public-key',
        response: { clientDataJSON: 'AQI', attestationObject: 'AwQ', transports: ['internal'] } } } }])
  })
  it('keeps step-up bound to authenticated endpoints and preserves assertion bytes', async () => {
    const get = vi.fn().mockResolvedValue({ id: 'a2V5', rawId: Uint8Array.from([107, 101, 121]).buffer,
      type: 'public-key', response: { clientDataJSON: Uint8Array.from([1]).buffer,
        authenticatorData: Uint8Array.from([2]).buffer, signature: Uint8Array.from([3]).buffer, userHandle: null } })
    vi.stubGlobal('navigator', { credentials: { get } })
    request.mockResolvedValueOnce({ challengeId: 'step-up', publicKey: { challenge: 'AQI' } }).mockResolvedValueOnce({ user: { id: 'owner' } })
    await passkeyApi.authenticate(true)
    expect(request.mock.calls[0]).toEqual(['/v1/auth/passkeys/step-up/options', { method: 'POST', auth: true }])
    expect(request.mock.calls[1][0]).toBe('/v1/auth/passkeys/step-up')
    expect(request.mock.calls[1][1]).toMatchObject({ auth: true, body: { challengeId: 'step-up',
      credential: { response: { clientDataJSON: 'AQ', authenticatorData: 'Ag', signature: 'Aw', userHandle: null } } } })
  })
  it('never submits a cancelled browser ceremony for authentication', async () => {
    vi.stubGlobal('navigator', { credentials: { get: vi.fn().mockResolvedValue(null) } })
    request.mockResolvedValueOnce({ challengeId: 'cancelled', publicKey: { challenge: 'AQI' } })
    await expect(passkeyApi.authenticate()).rejects.toThrow('cancelled')
    expect(request).toHaveBeenCalledTimes(1)
  })
})

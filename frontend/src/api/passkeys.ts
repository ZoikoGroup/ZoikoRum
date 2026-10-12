import { api } from './client'
import type { AuthResult } from './auth'

type Ceremony = { challengeId: string; publicKey: Record<string, unknown> }
export type Passkey = { id: string; label: string; createdAt: string }
function bytes(value: string): ArrayBuffer {
  const s = atob(value.replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(s, c => c.charCodeAt(0)).buffer
}
function encoded(value: ArrayBuffer): string {
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
function serialize(credential: PublicKeyCredential) {
  const response = credential.response
  return { id: credential.id, rawId: encoded(credential.rawId), type: credential.type,
    response: response instanceof AuthenticatorAttestationResponse
      ? { clientDataJSON: encoded(response.clientDataJSON), attestationObject: encoded(response.attestationObject), transports: response.getTransports() }
      : { clientDataJSON: encoded(response.clientDataJSON), authenticatorData: encoded((response as AuthenticatorAssertionResponse).authenticatorData),
          signature: encoded((response as AuthenticatorAssertionResponse).signature),
          userHandle: (response as AuthenticatorAssertionResponse).userHandle ? encoded((response as AuthenticatorAssertionResponse).userHandle!) : null } }
}
export const passkeyApi = {
  list: () => api<Passkey[]>('/v1/me/passkeys'),
  remove: (id: string) => api<void>(`/v1/me/passkeys/${id}`, { method: 'DELETE' }),
  async register(label: string) {
    const c = await api<Ceremony>('/v1/me/passkeys/options', { method: 'POST' })
    const o = c.publicKey as unknown as PublicKeyCredentialCreationOptions
    o.challenge = bytes(c.publicKey.challenge as string)
    o.user = { ...o.user, id: bytes((c.publicKey.user as { id: string }).id) }
    o.excludeCredentials = (c.publicKey.excludeCredentials as { id: string; type: 'public-key' }[]).map(k => ({ ...k, id: bytes(k.id) }))
    const credential = await navigator.credentials.create({ publicKey: o }) as PublicKeyCredential | null
    if (!credential) throw new Error('Passkey registration was cancelled')
    await api('/v1/me/passkeys', { method: 'POST', body: { challengeId: c.challengeId, credential: serialize(credential), label } })
  },
  async authenticate(stepUp = false): Promise<AuthResult> {
    const path = stepUp ? '/v1/auth/passkeys/step-up' : '/v1/auth/passkeys'
    const c = await api<Ceremony>(`${path}/options`, { method: 'POST', auth: stepUp })
    const o = c.publicKey as unknown as PublicKeyCredentialRequestOptions
    o.challenge = bytes(c.publicKey.challenge as string)
    const credential = await navigator.credentials.get({ publicKey: o }) as PublicKeyCredential | null
    if (!credential) throw new Error('Passkey authentication was cancelled')
    return api<AuthResult>(stepUp ? path : `${path}/verify`, { method: 'POST', auth: stepUp,
      body: { challengeId: c.challengeId, credential: serialize(credential) } })
  },
}

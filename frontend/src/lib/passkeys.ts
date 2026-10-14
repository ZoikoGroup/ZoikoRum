/* Passkeys (WebAuthn) in the browser: the server sends options as JSON (base64url strings); the browser API needs binary
   buffers, and its answer goes back to the server as JSON. Nothing secret leaves the device: only a signature. */

const toBytes = (b64url: string) => {
  const b64 = b64url.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (b64url.length % 4)) % 4)
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))
}
const toB64url = (buf: ArrayBuffer | null) =>
  buf ? btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '') : null

type Json = Record<string, unknown>
interface Descriptor { id: string; type: 'public-key'; transports?: string[] }

export const passkeysSupported = () => typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials

const descriptors = (list?: Descriptor[]) =>
  (list ?? []).map((d) => ({ ...d, id: toBytes(d.id), transports: d.transports as AuthenticatorTransport[] | undefined }))

/** Create a passkey on this device from the server's registration options. */
export async function createPasskey(options: Json): Promise<Json> {
  const o = options as unknown as PublicKeyCredentialCreationOptions & { challenge: string; user: { id: string }; excludeCredentials?: Descriptor[] }
  const cred = await navigator.credentials.create({
    publicKey: { ...o, challenge: toBytes(o.challenge), user: { ...o.user, id: toBytes(o.user.id) }, excludeCredentials: descriptors(o.excludeCredentials) },
  }) as PublicKeyCredential | null
  if (!cred) throw new Error('No passkey was created')
  const r = cred.response as AuthenticatorAttestationResponse
  return {
    id: cred.id, rawId: toB64url(cred.rawId), type: cred.type, clientExtensionResults: cred.getClientExtensionResults(),
    response: { clientDataJSON: toB64url(r.clientDataJSON), attestationObject: toB64url(r.attestationObject),
      transports: typeof r.getTransports === 'function' ? r.getTransports() : [] },
  }
}

/** Sign the server's challenge with a passkey on this device. */
export async function signWithPasskey(options: Json): Promise<Json> {
  const o = options as unknown as PublicKeyCredentialRequestOptions & { challenge: string; allowCredentials?: Descriptor[] }
  const cred = await navigator.credentials.get({
    publicKey: { ...o, challenge: toBytes(o.challenge), allowCredentials: descriptors(o.allowCredentials) },
  }) as PublicKeyCredential | null
  if (!cred) throw new Error('No passkey was used')
  const r = cred.response as AuthenticatorAssertionResponse
  return {
    id: cred.id, rawId: toB64url(cred.rawId), type: cred.type, clientExtensionResults: cred.getClientExtensionResults(),
    response: { clientDataJSON: toB64url(r.clientDataJSON), authenticatorData: toB64url(r.authenticatorData),
      signature: toB64url(r.signature), userHandle: toB64url(r.userHandle) },
  }
}

/** The person closed the device prompt or it timed out: not an error worth showing in red. */
export const passkeyCancelled = (err: unknown) => err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')

import { api } from '../api/client'

/* Browser push notifications: this device subscribes with the server's public VAPID key. */

export const pushSupported = () => typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window

function keyBytes(base64url: string): Uint8Array {
  const pad = '='.repeat((4 - (base64url.length % 4)) % 4)
  const raw = atob((base64url + pad).replace(/-/g, '+').replace(/_/g, '/'))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

export async function pushKey(): Promise<string | null> {
  return (await api<{ publicKey: string | null }>('/v1/push/key', { auth: false })).publicKey
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const reg = await navigator.serviceWorker.getRegistration('/sw.js')
  return reg ? reg.pushManager.getSubscription() : null
}

export async function enablePush(): Promise<void> {
  const key = await pushKey()
  if (!key) throw new Error('Push notifications are not available on this server.')
  if (await Notification.requestPermission() !== 'granted') throw new Error('Notifications are blocked for this site in your browser settings.')
  const reg = await navigator.serviceWorker.register('/sw.js')
  await navigator.serviceWorker.ready
  const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) as BufferSource })
  const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } }
  await api('/v1/push/subscriptions', { method: 'POST', body: { endpoint: json.endpoint, keys: json.keys } })
}

export async function disablePush(): Promise<void> {
  const sub = await currentSubscription()
  if (!sub) return
  await api('/v1/push/subscriptions/remove', { method: 'POST', body: { endpoint: sub.endpoint } }).catch(() => {})
  await sub.unsubscribe()
}

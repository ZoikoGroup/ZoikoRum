import { api } from './client'
import type { User } from './auth'

/* Settings: profile details, signed-in devices, privacy requests, notification preferences. */

export interface DeviceSession { id: string; device: string | null; authStrength: string; signedInAt: string; current: boolean }
/** ACCESS: RECEIVED -> COMPLETED (download until expiresAt). ERASURE: SCHEDULED -> COMPLETED | BLOCKED | CANCELLED. */
export interface DataRequest {
  id: string; requestType: 'ACCESS' | 'ERASURE'; status: string; createdAt: string; completedAt: string | null
  scheduledFor: string | null; expiresAt: string | null; downloadable: boolean; reasons: string[]; retained: Record<string, string>
}
export interface NotificationPreferences { email: boolean; inApp: boolean; sms: boolean; marketing: boolean; mandatoryNotice?: string }
export type ProfileDetails = User & { phone: string | null; language: string; timeZone: string | null }

export const accountApi = {
  me: () => api<ProfileDetails>('/v1/me'),
  update: (body: { displayName?: string; phone?: string; language?: string; timeZone?: string }) =>
    api<ProfileDetails>('/v1/me', { method: 'PATCH', body }),
  sessions: () => api<DeviceSession[]>('/v1/me/sessions'),
  signOutDevice: (id: string) => api<void>(`/v1/me/sessions/${id}`, { method: 'DELETE' }),
  dataRequests: () => api<DataRequest[]>('/v1/me/data-requests'),
  requestData: (requestType: 'ACCESS' | 'ERASURE') => api<DataRequest>('/v1/me/data-requests', { method: 'POST', body: { requestType } }),
  cancelDeletion: (id: string) => api<DataRequest>(`/v1/me/data-requests/${id}/cancel`, { method: 'POST' }),
  downloadData: (id: string) => api<Blob>(`/v1/me/data-requests/${id}/download`, { blob: true }),
  notifications: () => api<NotificationPreferences>('/v1/notification-preferences'),
  setNotifications: (body: NotificationPreferences) =>
    api<NotificationPreferences>('/v1/notification-preferences', { method: 'PUT', body }),
}

/** A readable device name from a browser user-agent string. */
export function deviceName(ua: string | null): string {
  if (!ua) return 'Unknown device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : 'Browser'
  const os = /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : ''
  return os ? `${browser} on ${os}` : browser
}

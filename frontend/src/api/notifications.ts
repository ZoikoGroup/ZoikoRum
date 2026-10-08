import { api } from './client'

export interface Notification { id: string; title: string; body: string; url: string; notice: Record<string, string> | null; mandatory: boolean; readAt: string | null; createdAt: string; emailStatus: string }
export interface Endpoint { id: string; organizationId: string; url: string; eventTypes: string[]; enabled: boolean }
export interface Delivery { id: string; endpointId: string; eventType: string; status: string; attempts: number; createdAt: string }
export interface DeliveryAttempt { attempt: number; responseStatus: number | null; error: string | null; createdAt: string }
export const notificationApi = {
  inbox: (cursor?: string) => api<{ items: Notification[]; nextCursor: string | null }>(`/v1/notifications${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`),
  count: () => api<{ unread: number }>('/v1/notifications/unread-count'),
  read: (id: string) => api<Notification>(`/v1/notifications/${id}/read`, { method: 'POST' }),
  eventTypes: () => api<{ eventType: string; label: string }[]>('/v1/webhook-event-types'),
  endpoints: (orgId: string) => api<Endpoint[]>(`/v1/webhook-endpoints?organizationId=${orgId}`),
  createEndpoint: (organizationId: string, url: string, eventTypes: string[]) => api<Endpoint & { secret: string }>('/v1/webhook-endpoints', { method: 'POST', body: { organizationId, url, eventTypes } }),
  enable: (id: string, enabled: boolean) => api<Endpoint>(`/v1/webhook-endpoints/${id}`, { method: 'PATCH', body: { enabled } }),
  test: (id: string) => api(`/v1/webhook-endpoints/${id}/test`, { method: 'POST' }),
  deliveries: (id: string, cursor?: string) => api<{ items: Delivery[]; nextCursor: string | null }>(`/v1/webhook-deliveries?endpointId=${id}${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`),
  replay: (id: string) => api(`/v1/webhook-deliveries/${id}/replay`, { method: 'POST' }),
  attempts: (id: string) => api<DeliveryAttempt[]>(`/v1/webhook-deliveries/${id}/attempts`),
}

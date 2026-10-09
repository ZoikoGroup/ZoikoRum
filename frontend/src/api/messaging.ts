import { api } from './client'

export type MessageContextType = 'PROPOSAL_REQUEST' | 'CONTRACT' | 'DISPUTE'

export interface MessageAttachment {
  id: string
  name: string
  contentType: string
  size: number
  sha256: string
  fileVersion: number
  uploadedAt: string
}

export interface ConversationMessage {
  id: string
  sequence: number
  senderIdentityId: string | null
  senderName: string
  body: string
  attachments: MessageAttachment[]
  contentHash: string
  sentAt: string
}

export interface MessageThread {
  id: string
  contextType: MessageContextType
  contextId: string
  title: string
  locked: boolean
  lockReason: string | null
  canSend: boolean
  unreadCount: number
  lastSequence: number
  updatedAt: string
  createdAt: string
  counterpartName: string
  viewerRole: 'BUYER' | 'PROFESSIONAL'
  professionalId: string
  photoUrl: string | null
  headline: string | null
  country: string | null
  lastMessage: string
  lastMessageFromSystem: boolean
}

interface Page<T> {
  items: T[]
  nextCursor: string | null
}

const T = '/v1/threads'
const idem = () => ({ 'Idempotency-Key': crypto.randomUUID() })

export interface MessageHit { threadId: string; threadTitle: string; sequence: number | null; senderName: string | null; snippet: string; sentAt: string }

export const messagingApi = {
  summary: () => api<{ unreadThreads: number; unreadMessages: number }>(`${T}/summary`),
  /** Messages and conversations the viewer can open, newest first (Global Search). */
  search: (q: string) => api<MessageHit[]>('/v1/messaging/search', { query: { q, limit: '5' } }),
  list: (cursor?: string) => api<Page<MessageThread>>(T, {
    query: { limit: '100', ...(cursor ? { cursor } : {}) },
  }),
  open: (contextType: MessageContextType, contextId: string) =>
    api<MessageThread>(T, { method: 'POST', body: { contextType, contextId }, headers: idem() }),
  get: (threadId: string) => api<MessageThread>(`${T}/${threadId}`),
  messages: (threadId: string, before?: number) =>
    api<Page<ConversationMessage>>(`${T}/${threadId}/messages`, {
      query: { limit: '100', ...(before ? { before: String(before) } : {}) },
    }),
  send: (threadId: string, body: string, attachments: string[], key?: string) =>
    api<ConversationMessage>(`${T}/${threadId}/messages`, {
      method: 'POST', body: { body, attachments }, headers: key ? { 'Idempotency-Key': key } : idem(),
    }),
  markRead: (threadId: string, throughSequence: number) =>
    api<void>(`${T}/${threadId}/read`, { method: 'POST', body: { throughSequence } }),
  upload: (threadId: string, name: string, dataBase64: string) =>
    api<MessageAttachment>(`${T}/${threadId}/attachments`, {
      method: 'POST', body: { name, dataBase64 }, headers: idem(),
    }),
  download: (threadId: string, attachmentId: string) =>
    api<Blob>(`${T}/${threadId}/attachments/${attachmentId}`, { blob: true }),
}

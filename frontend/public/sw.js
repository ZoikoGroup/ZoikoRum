/* Zoikorum service worker: shows push notifications and opens their link. It caches nothing. */
self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch { data = { title: 'Zoikorum', body: event.data ? event.data.text() : '' } }
  event.waitUntil(self.registration.showNotification(data.title || 'Zoikorum', {
    body: data.body || '', tag: data.tag, icon: '/logo.png', data: { url: data.url || '/' },
  }))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = (event.notification.data && event.notification.data.url) || '/'
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((wins) => {
    for (const w of wins) { if (w.url.startsWith(self.location.origin) && 'focus' in w) { w.navigate(url); return w.focus() } }
    return self.clients.openWindow(url)
  }))
})

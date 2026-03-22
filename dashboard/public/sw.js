const CACHE_NAME = 'hopefx-v9.5.0'
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
]

// Install: Cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS)
    })
  )
  self.skipWaiting()
})

// Activate: Clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      )
    })
  )
  self.clients.claim()
})

// Fetch: Network first, cache fallback
self.addEventListener('fetch', (event) => {
  const { request } = event
  
  // Skip non-GET requests
  if (request.method !== 'GET') return
  
  // API calls: Network only
  if (request.url.includes('/api/')) {
    event.respondWith(fetch(request))
    return
  }
  
  // Static assets: Cache first
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached
      
      return fetch(request).then((response) => {
        // Cache successful responses
        if (response.ok && response.type === 'basic') {
          const clone = response.clone()
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, clone)
          })
        }
        return response
      })
    })
  )
})

// Background sync for offline orders
self.addEventListener('sync', (event) => {
  if (event.tag === 'pending-orders') {
    event.waitUntil(processPendingOrders())
  }
})

async function processPendingOrders() {
  const db = await openDB('hopefx-orders', 1)
  const orders = await db.getAll('pending')
  
  for (const order of orders) {
    try {
      const response = await fetch('/api/v1/trades', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(order)
      })
      
      if (response.ok) {
        await db.delete('pending', order.id)
      }
    } catch (error) {
      console.error('Failed to sync order:', error)
    }
  }
}

// Push notifications
self.addEventListener('push', (event) => {
  const data = event.data.json()
  
  event.waitUntil(
    self.registration.showNotification('HOPEFX Alert', {
      body: data.message,
      icon: '/icon-192.png',
      badge: '/badge-72.png',
      tag: data.id,
      requireInteraction: true,
      actions: [
        { action: 'view', title: 'View' },
        { action: 'dismiss', title: 'Dismiss' }
      ]
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  
  if (event.action === 'view') {
    event.waitUntil(
      clients.openWindow(`/trading?alert=${event.notification.tag}`)
    )
  }
})

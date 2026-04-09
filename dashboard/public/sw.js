/* jshint esversion: 6 */
const CACHE_NAME = 'hopefx-v9.5.0';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/manifest.json',
  '/icon-192.png',
  '/icon-512.png'
];

// Install: Cache static assets
self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate: Clean old caches
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(cacheNames) {
      return Promise.all(
        cacheNames
          .filter(function(name) { return name !== CACHE_NAME; })
          .map(function(name) { return caches.delete(name); })
      );
    })
  );
  self.clients.claim();
});

// Fetch: Network first, cache fallback
self.addEventListener('fetch', function(event) {
  var request = event.request;

  // Skip non-GET requests
  if (request.method !== 'GET') { return; }

  // API calls: Network only
  if (request.url.includes('/api/')) {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets: Cache first
  event.respondWith(
    caches.match(request).then(function(cached) {
      if (cached) { return cached; }

      return fetch(request).then(function(response) {
        // Cache successful responses
        if (response.ok && response.type === 'basic') {
          var clone = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(request, clone);
          });
        }
        return response;
      });
    })
  );
});

// Background sync for offline orders
self.addEventListener('sync', function(event) {
  if (event.tag === 'pending-orders') {
    event.waitUntil(processPendingOrders());
  }
});

function processPendingOrders() {
  return openDB('hopefx-orders', 1).then(function(db) {
    return db.getAll('pending').then(function(orders) {
      var tasks = orders.map(function(order) {
        return fetch('/api/v1/trades', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(order)
        }).then(function(response) {
          if (response.ok) {
            return db.delete('pending', order.id);
          }
        }).catch(function(error) {
          console.error('Failed to sync order:', error);
        });
      });
      return Promise.all(tasks);
    });
  });
}

// Push notifications
self.addEventListener('push', function(event) {
  var data = event.data.json();

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
  );
});

self.addEventListener('notificationclick', function(event) {
  event.notification.close();

  if (event.action === 'view') {
    event.waitUntil(
      clients.openWindow('/trading?alert=' + event.notification.tag)
    );
  }
});

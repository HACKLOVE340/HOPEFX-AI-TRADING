// HOPEFX PWA Service Worker
const CACHE_NAME = 'hopefx-v1';
const STATIC_ASSETS = [
    '/',
    '/static/css/main.css',
    '/static/js/app.js',
    '/static/icons/icon-192x192.png',
    '/static/icons/icon-512x512.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => cache.addAll(STATIC_ASSETS))
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
    // Skip non-GET requests
    if (event.request.method !== 'GET') return;
    
    // API calls - network only with timeout
    if (event.request.url.includes('/api/')) {
        event.respondWith(
            fetch(event.request)
                .catch(() => caches.match(event.request))
        );
        return;
    }
    
    // Static assets - cache first
    event.respondWith(
        caches.match(event.request)
            .then((response) => {
                if (response) return response;
                return fetch(event.request)
                    .then((fetchResponse) => {
                        // Cache new static assets
                        if (fetchResponse.status === 200) {
                            const clone = fetchResponse.clone();
                            caches.open(CACHE_NAME)
                                .then((cache) => cache.put(event.request, clone));
                        }
                        return fetchResponse;
                    });
            })
    );
});

// Background sync for offline orders
self.addEventListener('sync', (event) => {
    if (event.tag === 'sync-orders') {
        event.waitUntil(syncPendingOrders());
    }
});

async function syncPendingOrders() {
    const db = await openDB('hopefx-offline', 1);
    const orders = await db.getAll('pendingOrders');
    
    for (const order of orders) {
        try {
            const response = await fetch('/api/orders', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(order)
            });
            
            if (response.ok) {
                await db.delete('pendingOrders', order.id);
                // Notify user
                self.registration.showNotification('Order Synced', {
                    body: `Order ${order.id} has been executed`,
                    icon: '/static/icons/icon-192x192.png'
                });
            }
        } catch (error) {
            console.error('Sync failed for order:', order.id);
        }
    }
}

// Push notifications
self.addEventListener('push', (event) => {
    const data = event.data.json();
    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: '/static/icons/icon-192x192.png',
            badge: '/static/icons/badge-72x72.png',
            data: data.url,
            actions: [
                { action: 'view', title: 'View' },
                { action: 'dismiss', title: 'Dismiss' }
            ]
        })
    );
});

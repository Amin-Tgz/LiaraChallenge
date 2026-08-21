const IMAGE_CACHE = 'liara-assistant-images-v1'

self.addEventListener('install', () => self.skipWaiting())

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key.startsWith('liara-assistant-images-') && key !== IMAGE_CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET' || request.destination !== 'image') return

  event.respondWith(
    caches.open(IMAGE_CACHE).then(async (cache) => {
      const cached = await cache.match(request)
      if (cached) return cached

      const response = await fetch(request)
      if (response.ok || response.type === 'opaque') {
        event.waitUntil(cache.put(request, response.clone()).catch(() => undefined))
      }
      return response
    }),
  )
})

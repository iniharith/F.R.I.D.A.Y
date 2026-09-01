const CACHE_NAME = "friday-hud-v2";
const PRECACHE = [
  "/",
  "/static/style.css",
  "/static/app.js",
  "/manifest.json",
  "/static/icon-192.png",
  "/static/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || e.request.url.includes("/ws") || e.request.url.includes("/health")) return;
  e.respondWith(
    fetch(e.request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(e.request, copy));
      return response;
    }).catch(async () => {
      const cached = await caches.match(e.request);
      if (cached) return cached;
      return e.request.mode === "navigate" ? caches.match("/") : Response.error();
    })
  );
});

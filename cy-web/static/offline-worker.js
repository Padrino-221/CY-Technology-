const CACHE = "cy-offline-v1";
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("message", event => {
    if (event.data === "clear-pages") event.waitUntil(caches.delete(CACHE));
});
self.addEventListener("fetch", event => {
    const request = event.request;
    const url = new URL(request.url);
    const asset = url.pathname.startsWith("/static/");
    if (request.method !== "GET" || url.origin !== self.location.origin ||
        (!asset && request.mode !== "navigate")) return;
    event.respondWith((async () => {
        const cache = await caches.open(CACHE);
        try {
            const response = await fetch(request);
            if (response.ok && !response.redirected && (asset || response.headers.has("X-CY-Offline-Page"))) {
                await cache.put(request, response.clone()).catch(() => {});
            } else if (!asset) {
                await cache.delete(request);
            }
            return response;
        } catch {
            return await cache.match(request) || new Response(
                "This page has not been saved for offline use. Go back to a page you opened while connected.",
                {status: 503, headers: {"Content-Type": "text/plain; charset=utf-8"}}
            );
        }
    })());
});

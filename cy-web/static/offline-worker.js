// Existing registrations fetch this replacement and retire themselves.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => {
    event.waitUntil((async () => {
        for (const name of await caches.keys()) {
            if (name.startsWith("cy-offline-")) await caches.delete(name);
        }
        await self.registration.unregister();
    })());
});

// One-time cleanup for browsers that used the former offline feature.
(async () => {
    try {
        if ("serviceWorker" in navigator) {
            for (const registration of await navigator.serviceWorker.getRegistrations()) {
                const worker = registration.active || registration.waiting || registration.installing;
                if (worker && new URL(worker.scriptURL).pathname === "/offline-worker.js") {
                    await registration.unregister();
                }
            }
        }
        if ("caches" in window) {
            for (const name of await caches.keys()) {
                if (name.startsWith("cy-offline-")) await caches.delete(name);
            }
        }
        if ("indexedDB" in window) indexedDB.deleteDatabase("cy-pending");
    } catch (error) {
        console.warn("Could not complete cleanup of the former offline feature.", error);
    }
})();

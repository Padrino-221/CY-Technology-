(() => {
    const panel = document.querySelector("[data-offline-user]");
    if (!panel || !window.isSecureContext || !("serviceWorker" in navigator) || !window.indexedDB) return;
    const user = panel.dataset.offlineUser;
    const revision = Number(panel.dataset.revision);
    const status = panel.querySelector("[role=status]");
    const list = panel.querySelector("ul");
    const operation = /^\/(?:(?:customers|inventory|sales|payments)\/(?:new|\d+\/(?:edit|delete))|payments\/\d+|inventory\/\d+\/release|sales\/\d+\/(?:return|refund)|settings)\/$/;
    let syncing = false;
    let queueMode = !navigator.onLine;
    const db = new Promise((resolve, reject) => {
        const request = indexedDB.open("cy-pending", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("changes", {keyPath: "id"});
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
    });

    async function store(mode, action) {
        const database = await db;
        return new Promise((resolve, reject) => {
            const tx = database.transaction("changes", mode);
            const request = action(tx.objectStore("changes"));
            tx.oncomplete = () => resolve(request.result);
            tx.onabort = () => reject(tx.error);
        });
    }

    async function pending() {
        return (await store("readonly", entries => entries.getAll()))
            .filter(entry => entry.user === user)
            .sort((a, b) => a.created - b.created);
    }

    async function show() {
        const entries = await pending();
        panel.hidden = navigator.onLine && !entries.length && !queueMode;
        status.textContent = entries.length
            ? `${entries.length} change(s) saved on this device`
            : "Offline. Changes you submit will be saved on this device.";
        list.replaceChildren();
        for (const entry of entries) {
            const item = document.createElement("li");
            const link = document.createElement("a");
            link.href = entry.path;
            link.textContent = entry.label;
            item.append(link);
            if (entry.error) {
                item.append(` · ${entry.error} `);
                const review = document.createElement("button");
                review.type = "button";
                review.textContent = "Review values";
                review.addEventListener("click", () => {
                    const values = document.createElement("dl");
                    for (const [name, value] of entry.fields) {
                        const key = document.createElement("dt");
                        const data = document.createElement("dd");
                        key.textContent = name.replaceAll("_", " ");
                        data.textContent = typeof value === "string" ? value : value.name;
                        values.append(key, data);
                    }
                    review.replaceWith(values);
                });
                const discard = document.createElement("button");
                discard.type = "button";
                discard.textContent = "Discard queued change";
                discard.addEventListener("click", async () => {
                    if (!confirm("Discard this unsynced change?")) return;
                    const result = await response.json();
                    await store("readwrite", records => records.delete(entry.id));
                    await show();
                    if (entries.length === 1 && result.location && document.querySelector("form[data-saving-offline]")) {
                        location.assign(result.location);
                        return;
                    }
                    sync();
                });
                item.append(review, discard);
            }
            list.append(item);
        }
    }

    async function sync() {
        if (syncing || !navigator.onLine) return;
        syncing = true;
        try {
            const run = async () => {
                const entries = await pending();
                if (!entries.length || entries[0].error) return;
                const auth = await fetch("/offline-session/", {cache: "no-store"});
                if (!auth.ok) {
                    status.textContent = "Sign in to sync changes saved on this device.";
                    return;
                }
                const session = await auth.json();
                if (session.user !== user) return;
                for (const entry of entries) {
                    if (entry.error) break;
                    const body = new FormData();
                    for (const [name, value] of entry.fields) body.append(name, value);
                    const response = await fetch(entry.path, {method: "POST", body, headers: {
                        "X-CSRFToken": session.csrf, "X-CY-User": user,
                        "X-CY-Operation": entry.id, "X-CY-Revision": String(entry.revision),
                    }, redirect: "error"});
                    if (!response.ok) {
                        if ([400, 409, 413, 422].includes(response.status)) {
                            entry.error = response.status === 413
                                ? "The upload exceeds the hosted request limit. Resubmit with smaller photos."
                                : (await response.json()).error;
                            await store("readwrite", records => records.put(entry));
                            await show();
                        }
                        break;
                    }
                    const result = await response.json();
                    await store("readwrite", records => records.delete(entry.id));
                    await show();
                    if (entries.length === 1 && result.location && document.querySelector("form[data-saving-offline]")) {
                        location.assign(result.location);
                        return;
                    }
                    status.textContent = "Change synced. Refresh the page to see current records.";
                    panel.hidden = false;
                }
            };
            if (navigator.locks) await navigator.locks.request("cy-offline-sync", run);
            else await run();
        } catch {
            status.textContent = "Sync interrupted. Queued changes remain on this device.";
        } finally {
            syncing = false;
        }
    }

    document.addEventListener("submit", async event => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || form.method !== "post") return;
        const url = new URL(form.action);
        if (url.pathname === "/logout/") {
            navigator.serviceWorker.controller?.postMessage("clear-pages");
            return;
        }
        if (url.origin !== location.origin || !operation.test(url.pathname)) return;
        const limit = Number(form.dataset.uploadLimit);
        const bytes = [...form.querySelectorAll('input[type="file"]')]
            .flatMap(input => [...input.files]).reduce((total, file) => total + file.size, 0);
        if (limit && bytes > limit) {
            event.preventDefault();
            panel.hidden = false;
            status.textContent = "Choose photos totaling 4 MB or less per submission.";
            return;
        }
        // Persist first, even when the browser believes it is connected.
        queueMode = !navigator.onLine;
        event.preventDefault();
        if (form.dataset.savingOffline) return;
        form.dataset.savingOffline = "true";
        try {
            const fields = [...new FormData(form, event.submitter)].filter(([name, value]) =>
                name !== "csrfmiddlewaretoken" && (typeof value === "string" || value.name));
            await store("readwrite", records => records.add({
                id: crypto.randomUUID(), user, revision, fields, path: url.pathname + url.search,
                label: `${document.querySelector("h1")?.textContent || "Record"} · ${url.pathname}`,
                created: Date.now(),
            }));
            form.closest("dialog")?.close();
            await show();
            await sync();
        } catch {
            panel.hidden = false;
            status.textContent = "This change could not be saved on this device. Keep the form open and try again.";
        } finally {
            delete form.dataset.savingOffline;
        }
    });

    navigator.serviceWorker.register("/offline-worker.js").catch(() => {});
    navigator.storage?.persist?.().catch(() => {});
    addEventListener("offline", () => { queueMode = true; show(); });
    addEventListener("online", () => { queueMode = false; sync(); });
    panel.querySelector("button").addEventListener("click", sync);
    setInterval(sync, 15000);
    show().then(sync).catch(() => {
        panel.hidden = false;
        status.textContent = "Browser storage is unavailable.";
    });
})();

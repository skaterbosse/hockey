// ---------------------------------------------------------
// ✅ LocalSport PWA - Service Worker
// ---------------------------------------------------------

const CACHE_VERSION = "v3-localsport";
const APP_SHELL = [
  "/",                        // <-- GitHub Pages fix: root måste med
  "/hockey/",                 // <-- Required for GitHub Pages
  "/hockey/index.html",
  "/hockey/manifest.json",
  "/hockey/service-worker.js",

  // Ikoner (JetBlack versioner)
  "/hockey/icons/icon_120_jetblack_exact2.png",
  "/hockey/icons/icon_152_jetblack_exact2.png",
  "/hockey/icons/icon_167_jetblack_exact2.png",
  "/hockey/icons/icon_180_jetblack_exact2.png",
  "/hockey/icons/icon_192_jetblack_exact2.png",
  "/hockey/icons/icon_512_jetblack_exact2.png",
  "/hockey/icons/icon_1024_jetblack_exact2.png",

  // Social share images (OG + Instagram format)
  "/hockey/icons/promotional_og_1200x630.png",
  "/hockey/icons/promotional_social_1080x1080.png"
];

// ---------------------------------------------------------
// ✅ INSTALL (cache app shell)
// ---------------------------------------------------------
self.addEventListener("install", event => {
  console.log("⬇️  SW: install");

  event.waitUntil(
    caches.open(CACHE_VERSION).then(cache => {
      return cache.addAll(APP_SHELL);
    })
  );

  // Aktiv direkt
  self.skipWaiting();
});

// ---------------------------------------------------------
// ✅ ACTIVATE — rensa gamla SW versioner direkt
// ---------------------------------------------------------
self.addEventListener("activate", event => {
  console.log("⚡ SW: activate");

  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_VERSION)
          .map(oldKey => {
            console.log("🗑️ Rensar gammal cache:", oldKey);
            return caches.delete(oldKey);
          })
      )
    )
  );

  // Gör SW till active direkt (inga zombies)
  self.clients.claim();
});

// ---------------------------------------------------------
// ✅ FETCH HANDLER
// ---------------------------------------------------------
self.addEventListener("fetch", event => {
  const url = event.request.url;

  // ❌ MATCHDATA ska INTE cachas
  if (url.includes("games.csv") || url.includes("Clubs_Organisatons_logos")) {
    return fetch(event.request);
  }

  // ✅ Network First för index.html (ger auto-refresh på GitHub Pages)
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then(res => {
          cachePut(event.request, res.clone());
          return res;
        })
        .catch(() => caches.match("/hockey/index.html"))
    );
    return;
  }

  // ✅ Cache first för app shell (snabb uppstart)
  event.respondWith(
    caches.match(event.request).then(cachedRes => {
      return (
        cachedRes ||
        fetch(event.request).then(networkRes => {
          cachePut(event.request, networkRes.clone());
          return networkRes;
        }).catch(() => cachedRes)
      );
    })
  );
});

// ---------------------------------------------------------
// ✅ Hjälpfunktion – cache PUT (endast för statiska filer)
// ---------------------------------------------------------
function cachePut(request, response) {
  if (!response || response.status !== 200) return;
  caches.open(CACHE_VERSION).then(cache => cache.put(request, response));
}

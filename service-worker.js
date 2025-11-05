const CACHE_NAME = "localsport-v4";
const ASSETS_TO_CACHE = [
  "/hockey/index.html",
  "/hockey/manifest.json",

  // ✅ Poster-baserade app-ikoner
  "/hockey/icons/local_sport_promotional_poster_120.png",
  "/hockey/icons/local_sport_promotional_poster_152.png",
  "/hockey/icons/local_sport_promotional_poster_167.png",
  "/hockey/icons/local_sport_promotional_poster_180.png",
  "/hockey/icons/local_sport_promotional_poster_192.png",
  "/hockey/icons/local_sport_promotional_poster_512.png",
  "/hockey/icons/local_sport_promotional_poster_1024.png",

  // ✅ Favicons JetBlack (för browser tabs)
  "/hockey/icons/icon_32_jetblack_exact2.png",
  "/hockey/icons/icon_120_jetblack_exact2.png",
  "/hockey/icons/icon_152_jetblack_exact2.png",
  "/hockey/icons/icon_167_jetblack_exact2.png",
  "/hockey/icons/icon_180_jetblack_exact2.png",
  "/hockey/icons/icon_192_jetblack_exact2.png",
  "/hockey/icons/icon_512_jetblack_exact2.png",
  "/hockey/icons/icon_1024_jetblack_exact2.png",

  // ✅ Social share images
  "/hockey/icons/promotional_og_1200x630.png",
  "/hockey/icons/promotional_social_1080x1080.png"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS_TO_CACHE))
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
});

self.addEventListener("fetch", e => {
  e.respondWith(
    caches.match(e.request).then(cached => cached || fetch(e.request))
  );
});

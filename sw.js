// Service worker simples: deixa o app instalável e guarda em cache a
// última versão vista, pra abrir mais rápido (e mostrar algo mesmo sem
// internet) — mas sempre tenta buscar dados novos primeiro.
const CACHE = "vagas-porto-v1";
const ARQUIVOS_BASICOS = ["./", "./index.html", "./manifest.json"];

self.addEventListener("install", (evt) => {
  evt.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ARQUIVOS_BASICOS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evt) => {
  evt.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (evt) => {
  if (evt.request.method !== "GET") return;
  evt.respondWith(
    fetch(evt.request)
      .then((resp) => {
        const copia = resp.clone();
        caches.open(CACHE).then((cache) => cache.put(evt.request, copia));
        return resp;
      })
      .catch(() => caches.match(evt.request))
  );
});

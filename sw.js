// Service worker simples: deixa o app instalável e guarda em cache a
// última versão vista, pra abrir mais rápido (e mostrar algo mesmo sem
// internet) — mas sempre tenta buscar dados novos primeiro.
const CACHE = "vagas-porto-v2";
const ARQUIVOS_BASICOS = [
  "./",
  "./index.html",
  "./manifest.json",
  "./compatibilidade.js",
  "./config/perfil_hugo.json",
];

self.addEventListener("install", (evt) => {
  evt.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ARQUIVOS_BASICOS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (evt) => {
  evt.waitUntil(
    caches.keys()
      .then((nomes) => Promise.all(
        nomes
          .filter((nome) => nome.startsWith("vagas-porto-v") && nome !== CACHE)
          .map((nome) => caches.delete(nome))
      ))
      .then(() => self.clients.claim())
  );
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

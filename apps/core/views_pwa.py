"""PWA: deixa a plataforma instalável no celular (ícone na tela inicial, tela cheia) e com
uma página offline amigável, sem nenhum serviço ou dependência externa.

Três recursos públicos, servidos do próprio domínio (a CSP e o LoginRequiredMiddleware exigem
marcar como público):

- ``/manifest.webmanifest`` — nome, cores e ícones do app instalado;
- ``/sw.js`` — o service worker (precisa ficar na raiz para controlar todo o site);
- ``/offline/`` — a página mostrada quando não há internet.

LGPD: o service worker **nunca** guarda páginas com dados (navegações) nem ``/media/`` (fotos e
documentos). Só os arquivos públicos de ``/static/`` e a página offline entram no cache do
navegador, o que combina com o ``PrivatePagesNoStoreMiddleware``.
"""

import json

from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

THEME = "#2b45a6"       # --ds-primary
BACKGROUND = "#ffffff"

# Arquivos públicos que a página offline usa, pré-guardados na instalação para ela abrir sem internet.
SHELL = [
    "vendor/bootstrap.min.css",
    "css/ds-tokens.css",
    "css/ds-components.css",
    "img/favicon.svg",
    "img/icon-192.png",
    "img/icon-512.png",
]


@login_not_required
@cache_control(max_age=86400)
def manifest(request):
    data = {
        "name": "Plataforma Escolar",
        "short_name": "Escola",
        "description": "Atividades, notas, frequência e comunicação entre a escola e as famílias.",
        "lang": "pt-BR",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": BACKGROUND,
        "theme_color": THEME,
        "icons": [
            {"src": static("img/icon-192.png"), "sizes": "192x192", "type": "image/png",
             "purpose": "any maskable"},
            {"src": static("img/icon-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "any maskable"},
        ],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False),
                        content_type="application/manifest+json; charset=utf-8")


@login_not_required
@cache_control(max_age=3600)
def service_worker(request):
    offline = "/offline/"
    shell = json.dumps([offline] + [static(p) for p in SHELL])
    js = """\
// Service worker da Plataforma Escolar. Gerado por apps/core/views_pwa.py.
// LGPD: só guarda arquivos públicos de /static/ e a pagina offline. Paginas com dados e
// /media/ (fotos, documentos) vao sempre pela rede e nunca entram no cache.
const CACHE = "escola-v1";
const OFFLINE = "%(offline)s";
const SHELL = %(shell)s;

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === "navigate") {
    // Paginas: rede primeiro; sem internet, mostra a pagina offline. Nunca sao guardadas.
    event.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    // Arquivos publicos: usa o cache e atualiza em segundo plano.
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((cache) => cache.put(req, copy));
        return res;
      }))
    );
  }
  // /media/ e o resto: rede, sem cache.
});
""" % {"offline": offline, "shell": shell}
    return HttpResponse(js, content_type="application/javascript; charset=utf-8")


@login_not_required
def offline(request):
    return render(request, "offline.html", {"theme_color": THEME})

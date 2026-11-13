// Registra o service worker da plataforma (PWA instalável + página offline).
// Externo de propósito: a CSP (script-src 'self') não permite script embutido no HTML.
// Falhar aqui é inofensivo — o PWA é um extra; o site funciona sem ele.
(function () {
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  });
})();

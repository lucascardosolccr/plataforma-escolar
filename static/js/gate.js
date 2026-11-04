/* Portaria: distingue leitor USB de digitação e lê pela câmera onde o navegador permite.
   - Leitor USB de código de barras ou QR "digita" o código muito rápido e manda Enter: se os caracteres
     chegam em menos de ~35 ms cada, a origem é "leitor" (registrada como código de barras ou QR).
   - Câmera: usa a API nativa BarcodeDetector (Chrome no Android, por exemplo), sem biblioteca externa.
     Precisa de HTTPS (ou localhost). Onde não existe, o botão não aparece. */
(function () {
  "use strict";
  var form = document.querySelector("[data-gate-form]");
  if (!form) return;
  var input = form.querySelector("[data-gate-input]");
  var origin = form.querySelector("[data-gate-origin]");
  var times = [];

  input.addEventListener("keydown", function (ev) {
    if (ev.key.length === 1) times.push(performance.now());
  });
  form.addEventListener("submit", function () {
    if (origin.value.indexOf("camera") === 0) return;
    var fast = times.length >= 6;
    for (var i = 1; i < times.length && fast; i++) if (times[i] - times[i - 1] > 35) fast = false;
    origin.value = fast ? "leitor" : "teclado";
  });
  input.addEventListener("input", function () { if (!input.value) times = []; });

  var camBtn = form.querySelector("[data-gate-camera]");
  var video = form.querySelector("[data-gate-video]");
  var msg = form.querySelector("[data-gate-camera-msg]");
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices || !window.isSecureContext) return;
  camBtn.hidden = false;
  var stream = null;

  function stop() {
    if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
    stream = null; video.hidden = true;
  }

  camBtn.addEventListener("click", function () {
    if (stream) { stop(); return; }
    var detector;
    try { detector = new window.BarcodeDetector({ formats: ["qr_code", "code_128"] }); }
    catch (e) { msg.hidden = false; msg.textContent = "Este navegador não lê códigos pela câmera."; return; }
    navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } }).then(function (s) {
      stream = s; video.srcObject = s; video.hidden = false; video.play();
      msg.hidden = false; msg.textContent = "Aponte a câmera para o QR Code ou o código de barras.";
      var tick = function () {
        if (!stream) return;
        detector.detect(video).then(function (codes) {
          if (codes.length) {
            input.value = codes[0].rawValue;
            origin.value = codes[0].format === "qr_code" ? "camera-qr" : "camera-barras";
            stop(); form.submit();
          } else { setTimeout(tick, 250); }
        }).catch(function () { setTimeout(tick, 500); });
      };
      tick();
    }).catch(function () { msg.hidden = false; msg.textContent = "Sem permissão para usar a câmera."; });
  });
})();

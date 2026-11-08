/* Portaria: leitura contínua da carteirinha, sem recarregar a página e sem perder leitura.
   - Leitor USB (código de barras ou QR) funciona como teclado: "digita" o conteúdo muito rápido e manda Enter
     (ou Tab, em alguns modelos). Média abaixo de 40 ms por tecla = leitor; mais lenta = digitação.
   - Cada leitura vai ao servidor em segundo plano (fetch) e o campo fica livre na hora: o leitor pode ler o
     próximo cartão sem esperar a resposta. Com a página recarregando a cada leitura, as teclas do leitor que
     chegavam durante o recarregamento se perdiam.
   - Sem internet (ou com a sessão expirada), a leitura fica guardada neste navegador com o horário em que foi
     feita, corrigido pelo relógio do servidor, e é enviada sozinha quando a conexão volta. Só o texto lido fica
     guardado (nenhum nome ou dado do estudante).
   - O código digitado é conferido aqui mesmo pelo dígito verificador (Luhn mod 32), antes de ir ao servidor.
   - Som diferente para registrado, atraso, repetido e recusado (Web Audio, sem arquivo externo).
   - Câmera: API nativa BarcodeDetector (Chrome no Android, por exemplo), sem biblioteca externa. Precisa de
     HTTPS (ou localhost). Onde não existe, o botão não aparece. */
(function () {
  "use strict";
  var form = document.querySelector("[data-gate-form]");
  if (!form) return;
  var input = form.querySelector("[data-gate-input]");
  var origin = form.querySelector("[data-gate-origin]");
  var hint = form.querySelector("[data-gate-hint]");
  var soundBox = form.querySelector("[data-gate-sound]");
  var csrf = form.querySelector("input[name=csrfmiddlewaretoken]");
  var results = document.querySelector("[data-gate-results]");
  var recent = document.querySelector("[data-gate-recent]");
  var offlineBox = document.querySelector("[data-gate-offline]");
  var failedBox = document.querySelector("[data-gate-failed-box]");
  var failedList = document.querySelector("[data-gate-failed]");
  var URL_POST = location.pathname;
  var QKEY = "portaria-fila-v1", KKEY = "portaria-tipo", SKEY = "portaria-som", OKEY = "portaria-relogio";
  var KINDS = ["entrada", "saida", "auto"];
  var ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
  var times = [];

  // ------------------------------------------------------------------ preferências deste computador
  function load(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function store(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* modo privado */ } }
  function queue() { try { return JSON.parse(load(QKEY) || "[]"); } catch (e) { return []; } }
  function saveQueue(q) { store(QKEY, JSON.stringify(q)); }
  var offset = parseInt(load(OKEY) || "0", 10) || 0; // relógio do servidor menos o deste computador (ms)

  var savedKind = load(KKEY);
  if (KINDS.indexOf(savedKind) !== -1 && !new URLSearchParams(location.search).get("tipo")) {
    form.querySelector('[data-gate-kind][value="' + savedKind + '"]').checked = true;
  }
  Array.prototype.forEach.call(form.querySelectorAll("[data-gate-kind]"), function (radio) {
    radio.addEventListener("change", function () { store(KKEY, radio.value); input.focus(); });
  });
  if (load(SKEY) === "0") soundBox.checked = false;
  soundBox.addEventListener("change", function () { store(SKEY, soundBox.checked ? "1" : "0"); input.focus(); });
  function kind() { var r = form.querySelector("[data-gate-kind]:checked"); return r ? r.value : "entrada"; }

  // ------------------------------------------------------------------ conferência do código (igual ao servidor)
  function compact(raw) {
    raw = (raw || "").trim();
    if (raw.charAt(0) === "]" && raw.length > 3) raw = raw.slice(3); // identificador AIM (]Q1, ]C0)
    return raw.toUpperCase().replace(/[^0-9A-Z]/g, "");
  }
  function luhn32(body) {
    var factor = 2, total = 0, n = ALPHABET.length;
    for (var i = body.length - 1; i >= 0; i--) {
      var addend = factor * ALPHABET.indexOf(body.charAt(i));
      factor = factor === 2 ? 1 : 2;
      total += Math.floor(addend / n) + addend % n;
    }
    return ALPHABET.charAt((n - total % n) % n);
  }
  function problem(raw) {
    var c = compact(raw);
    if (c.indexOf("EC1") === 0 && c.length !== 9) return c.length === 22 ? null : "QR Code em formato desconhecido.";
    c = c.replace(/O/g, "0").replace(/[IL]/g, "1");
    if (c.length !== 9) return "O código tem 9 caracteres; foram " + c.length + ".";
    for (var i = 0; i < 9; i++) {
      if (ALPHABET.indexOf(c.charAt(i)) === -1) return "O caractere " + c.charAt(i) + " não existe no código.";
    }
    if (luhn32(c.slice(0, 8)) !== c.charAt(8)) return "O último caractere (verificador) não confere: confira o código.";
    return null;
  }
  // Leitor: média abaixo de 40 ms por tecla e no máximo um intervalo longo (o navegador ocupado com a
  // resposta anterior pode atrasar uma tecla). Ninguém digita 9 caracteres com média abaixo de 40 ms.
  // Usa o horário do evento (ev.timeStamp), que vem do sistema, e não a hora em que o script o processou.
  function fromScanner() {
    if (times.length < 6) return false;
    var slow = 0;
    for (var i = 1; i < times.length; i++) if (times[i] - times[i - 1] > 60) slow++;
    return slow <= 1 && (times[times.length - 1] - times[0]) / (times.length - 1) < 40;
  }
  function setHint(text, cls) { hint.textContent = text || ""; hint.className = "small mb-2 " + (cls || ""); }

  input.addEventListener("keydown", function (ev) {
    if (ev.key.length === 1) times.push(ev.timeStamp);
    if (ev.key === "Tab" && input.value && fromScanner()) { ev.preventDefault(); submit(); } // leitor que manda Tab
  });
  input.addEventListener("input", function () {
    if (!input.value) { times = []; setHint(""); return; }
    if (fromScanner() || compact(input.value).indexOf("EC1") === 0) { setHint(""); return; }
    var c = compact(input.value);
    if (c.length < 9) { setHint(""); return; }
    var err = problem(input.value);
    setHint(err || "Código válido. Aperte Enter.", err ? "text-danger" : "text-success");
  });

  // Leitor "digitando" com o foco fora do campo (depois de clicar num botão, por exemplo): as teclas vêm
  // para o campo em vez de se perderem.
  document.addEventListener("keydown", function (ev) {
    var t = ev.target;
    if (t === input || ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var typing = t && (t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable ||
      (t.tagName === "INPUT" && ["radio", "checkbox", "button", "submit"].indexOf(t.type) === -1));
    if (typing) return;
    if (ev.key.length === 1) {
      ev.preventDefault();
      input.focus();
      input.value += ev.key;
      times.push(ev.timeStamp);
    } else if (ev.key === "Enter" && input.value) {
      ev.preventDefault();
      submit();
    }
  });

  // ------------------------------------------------------------------ envio
  function submit() {
    if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event("submit", { cancelable: true }));
  }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var raw = input.value.trim();
    var src = origin.value.indexOf("camera") === 0 ? origin.value : (fromScanner() ? "leitor" : "teclado");
    origin.value = "teclado";
    input.value = "";
    times = [];
    setHint("");
    input.focus();
    if (!raw) return;
    if (src === "teclado") {
      var err = problem(raw);
      if (err) { showLocalError(err); beep("error"); return; }
    }
    send({ codigo: raw, tipo: kind(), origem: src, at: Date.now() + offset });
  });

  var chain = Promise.resolve();
  function send(item) {
    if (queue().length) { enqueue(item); flush(); return; } // mantém a ordem das leituras guardadas
    chain = chain.then(function () {
      return post(item, false).then(function (outcome) {
        if (outcome !== "ok") { enqueue(item); beep("offline"); }
      });
    });
  }

  function post(item, queued) {
    var body = new FormData();
    body.append("csrfmiddlewaretoken", csrf.value);
    body.append("codigo", item.codigo);
    body.append("tipo", item.tipo);
    body.append("origem", item.origem);
    if (queued) body.append("quando", new Date(item.at).toISOString());
    return fetch(URL_POST, { method: "POST", body: body, credentials: "same-origin",
                             headers: { "Accept": "application/json" } })
      .then(function (r) {
        var type = r.headers.get("Content-Type") || "";
        if (type.indexOf("application/json") !== -1 && r.ok) return r.json().then(function (data) { return show(data, item, queued); });
        if (r.status >= 500) return "server";
        return "session"; // página de login (sessão expirada) ou CSRF recusado
      })
      .catch(function () { return "network"; })
      .then(function (outcome) { status(outcome); return outcome; });
  }

  function show(data, item, queued) {
    if (data.server_time) { offset = data.server_time - Date.now(); store(OKEY, String(offset)); }
    if (data.recent_html) {
      var empty = recent.querySelector("[data-gate-recent-empty]");
      if (empty) empty.remove();
      recent.insertAdjacentHTML("afterbegin", data.recent_html);
      while (recent.children.length > 8) recent.lastElementChild.remove();
    }
    if (queued && data.status === "error") {
      var box = document.createElement("div");
      box.innerHTML = data.html;
      failed(item, box.textContent.replace(/\s+/g, " ").trim());
    } else if (!queued) {
      results.innerHTML = data.html;
      beep(data.status);
    }
    return "ok";
  }

  function showLocalError(message) {
    results.innerHTML = "";
    var card = document.createElement("section");
    card.className = "card mb-3 gate-result is-error";
    var bodyDiv = document.createElement("div");
    bodyDiv.className = "card-body";
    var title = document.createElement("p");
    title.className = "h5 mb-1";
    title.textContent = "Não registrado";
    var text = document.createElement("p");
    text.className = "mb-0";
    text.textContent = message;
    bodyDiv.appendChild(title);
    bodyDiv.appendChild(text);
    card.appendChild(bodyDiv);
    results.appendChild(card);
  }

  function failed(item, message) {
    var li = document.createElement("li");
    li.className = "py-1 border-bottom";
    var when = new Date(item.at - offset);
    li.textContent = when.toLocaleString("pt-BR") + " · " + item.codigo.slice(0, 24) + " · " + message;
    failedList.insertBefore(li, failedList.firstChild);
    failedBox.hidden = false;
  }

  // ------------------------------------------------------------------ leituras guardadas sem conexão
  function enqueue(item) {
    var q = queue();
    q.push({ codigo: item.codigo, tipo: item.tipo, origem: item.origem, at: item.at, tries: 0 });
    saveQueue(q);
    status("network");
  }

  var flushing = false;
  function flush() {
    var q = queue();
    if (flushing || !q.length) { status("ok"); return; }
    flushing = true;
    post(q[0], true).then(function (outcome) {
      var rest = queue();
      if (outcome === "ok") {
        rest.shift();
      } else if (outcome === "server") {
        rest[0].tries = (rest[0].tries || 0) + 1;
        if (rest[0].tries >= 5) failed(rest.shift(), "O servidor recusou cinco vezes. Registre à mão.");
      }
      saveQueue(rest);
      flushing = false;
      if (outcome === "ok" || (outcome === "server" && rest.length)) flush(); else status(outcome);
    });
  }

  var lastOutcome = "ok";
  function status(outcome) {
    lastOutcome = outcome || lastOutcome;
    var n = queue().length;
    if (!n) { offlineBox.hidden = true; offlineBox.textContent = ""; return; }
    var many = n === 1 ? "1 leitura guardada" : n + " leituras guardadas";
    var text = many + " neste computador, com o horário de cada uma. ";
    if (lastOutcome === "session") {
      text = "A sessão terminou: entre de novo para enviar. " + text + "Elas são enviadas sozinhas depois que você entrar.";
    } else if (lastOutcome === "server") {
      text = "O servidor não respondeu direito. " + text + "Nova tentativa em instantes.";
    } else {
      text = "Sem conexão com a plataforma. Pode continuar lendo: " + text +
        "Elas são enviadas sozinhas quando a conexão voltar, mesmo que esta página seja fechada e aberta de novo.";
    }
    offlineBox.textContent = text;
    offlineBox.className = "gate-offline mb-3 " + (lastOutcome === "session" ? "is-session" : "");
    offlineBox.hidden = false;
    if (lastOutcome === "session") {
      var link = document.createElement("a");
      link.href = location.pathname;
      link.className = "ms-1";
      link.textContent = "Entrar de novo";
      offlineBox.appendChild(link);
    }
  }

  window.addEventListener("online", flush);
  setInterval(flush, 15000);
  setTimeout(flush, 300);

  // ------------------------------------------------------------------ som
  var audio = null;
  var TONES = {
    ok: [[1046, 0.12]],
    late: [[784, 0.14], [784, 0.14]],
    existed: [[660, 0.08]],
    error: [[196, 0.45]],
    offline: [[523, 0.1], [392, 0.1]]
  };
  function beep(kindOfSound) {
    if (!soundBox.checked) return;
    try {
      audio = audio || new (window.AudioContext || window.webkitAudioContext)();
      var t = audio.currentTime + 0.01;
      (TONES[kindOfSound] || TONES.existed).forEach(function (tone) {
        var osc = audio.createOscillator(), gain = audio.createGain();
        osc.type = kindOfSound === "error" ? "square" : "sine";
        osc.frequency.value = tone[0];
        gain.gain.setValueAtTime(0.18, t);
        gain.gain.exponentialRampToValueAtTime(0.001, t + tone[1]);
        osc.connect(gain);
        gain.connect(audio.destination);
        osc.start(t);
        osc.stop(t + tone[1]);
        t += tone[1] + 0.06;
      });
    } catch (e) { /* sem áudio: a cor do quadro continua indicando o resultado */ }
  }

  // ------------------------------------------------------------------ câmera
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
            stop(); submit();
          } else { setTimeout(tick, 250); }
        }).catch(function () { setTimeout(tick, 500); });
      };
      tick();
    }).catch(function () { msg.hidden = false; msg.textContent = "Sem permissão para usar a câmera."; });
  });
})();

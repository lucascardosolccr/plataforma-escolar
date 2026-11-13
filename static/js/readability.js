// Legibilidade ao vivo nos formulários da equipe (Python puro no servidor, custo zero,
// sem dependência nova). Procura cada [data-readability], observa o textarea indicado em
// data-target e, enquanto a equipe escreve um comunicado ou mensagem à família, pede ao
// servidor o Índice de Facilidade de Leitura e mostra a faixa. Só envia o texto digitado:
// nenhum dado de aluno trafega aqui. Se algo falhar, some em silêncio — é recurso auxiliar.
(function () {
  "use strict";

  function render(r) {
    if (!r || r.empty) return "";
    if (!r.enough) {
      return '<span class="small text-body-secondary">Legibilidade: escreva ao menos ' +
        r.min_words + ' palavras para medir.</span>';
    }
    // Mesma convenção de cores do resto da plataforma: verde = fácil, azul = informativo, âmbar = atenção.
    var cls = r.band === "muito difícil" ? "state-ajustes"
            : r.band === "difícil" ? "state-aguardando" : "state-validado";
    var html = '<span class="small text-body-secondary">Legibilidade: </span>' +
      '<span class="chip chip-state ' + cls + '">' + r.band + '</span> ' +
      '<span class="small text-body-secondary">IFL ' + r.score + ' · leitura ~' + r.grade +
      ' · ' + r.words_per_sentence + ' palavras/frase.</span>';
    if (r.long_count) {
      html += '<br><span class="small">' + r.long_count + ' frase' + (r.long_count > 1 ? "s" : "") +
        ' com mais de 25 palavras: dividir costuma deixar o recado mais claro.</span>';
    }
    return html;
  }

  function setup(box) {
    var target = document.getElementById(box.getAttribute("data-target"));
    var url = box.getAttribute("data-url");
    var csrf = box.getAttribute("data-csrf");
    if (!target || !url) return;

    var timer = null;
    function run() {
      var data = new URLSearchParams();
      data.append("text", target.value || "");
      fetch(url, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrf },
        body: data.toString()
      }).then(function (resp) {
        return resp.ok ? resp.json() : null;
      }).then(function (j) {
        if (j) box.innerHTML = render(j.readability);
      }).catch(function () { /* silencioso */ });
    }

    target.addEventListener("input", function () {
      if (timer) { clearTimeout(timer); }
      timer = setTimeout(run, 450);
    });
    if ((target.value || "").trim()) { run(); }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var boxes = document.querySelectorAll("[data-readability]");
    for (var i = 0; i < boxes.length; i++) { setup(boxes[i]); }
  });
})();

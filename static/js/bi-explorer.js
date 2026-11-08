/* Painel interativo (estilo BI) do estudante e da turma.
 *
 * Carrega uma vez os fatos do período (apps/analytics/explorer.py) e recalcula tudo no navegador a cada
 * clique, sem recarregar a página:
 * - recortes (bimestre ou mês, disciplinas) e filtros ativos removíveis;
 * - filtro cruzado: clicar numa barra, numa faixa ou num estudante filtra (ou destaca) os outros visuais;
 * - arrastar na linha do tempo escolhe um intervalo de datas; arrastar na dispersão seleciona estudantes;
 * - cada visual tem "Tabela" (os mesmos números, acessíveis a leitor de tela);
 * - o estado fica no endereço (#bi:...), para voltar ao mesmo recorte ou mandar o link a um colega.
 *
 * As contas seguem as do servidor (bi.py): fórmula e nota mínima de cada disciplina, média geral = média das
 * médias por disciplina, frequência = (presenças + atrasos) / registros, entrega = entregues / com registro.
 * Sem dependências e sem estilo embutido (CSP 'self'): só atributos SVG e classes.
 */
(function () {
  "use strict";
  var root = document.querySelector("[data-bi-explorer]");
  if (!root || !window.fetch) return;
  var SVGNS = "http://www.w3.org/2000/svg";
  var WEEKDAYS = ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"];
  var MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  var BANDS = [["0–2", 0, 2], ["2–4", 2, 4], ["4–6", 4, 6], ["6–8", 6, 8], ["8–10", 8, 10.0001]];

  // ------------------------------------------------------------------ construção de elementos
  function attrs(n, a) {
    if (!a) return n;
    Object.keys(a).forEach(function (k) {
      var v = a[k];
      if (v === null || v === undefined || v === false) return;
      if (k === "text") n.textContent = v;
      else if (k === "on") Object.keys(v).forEach(function (ev) { n.addEventListener(ev, v[ev]); });
      else n.setAttribute(k, v === true ? "" : v);
    });
    return n;
  }
  function add(n, kids) {
    (Array.isArray(kids) ? kids : [kids]).forEach(function (k) {
      if (k === null || k === undefined || k === false) return;
      n.appendChild(typeof k === "string" || typeof k === "number" ? document.createTextNode(String(k)) : k);
    });
    return n;
  }
  // kids pode ser 0 (um número a mostrar): "kids || []" apagava o zero das tabelas.
  function h(tag, a, kids) { return add(attrs(document.createElement(tag), a), kids === undefined || kids === null ? [] : kids); }
  function s(tag, a, kids) { return add(attrs(document.createElementNS(SVGNS, tag), a), kids === undefined || kids === null ? [] : kids); }

  // ------------------------------------------------------------------ números e datas
  /* round() do Python: "metade para o par" sobre o valor binário exato. Com Math.round (metade para cima), 8,25
     virava 8,3 aqui e 8,2 no servidor; os números precisam bater com o relatório detalhado. */
  function round(v, d) {
    if (v === null || v === undefined || !isFinite(v)) return null;
    // toFixed(60) dá a expansão decimal exata do double (o Python arredonda sobre ela).
    var txt = Math.abs(v).toFixed(60), dot = txt.indexOf(".");
    var q = Number(txt.slice(0, dot) + txt.slice(dot + 1, dot + 1 + d));
    var rest = txt.slice(dot + 1 + d), first = rest.charAt(0), tail = /[1-9]/.test(rest.slice(1));
    if (first > "5" || (first === "5" && (tail || q % 2 === 1))) q += 1;
    return (v < 0 ? -q : q) / Math.pow(10, d);
  }
  function num(v, d) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return round(Number(v), d).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d });
  }
  function pct(a, b) { return b ? round(a / b * 100, 1) : null; }
  function mean(a) { return a.length ? a.reduce(function (x, y) { return x + y; }, 0) / a.length : null; }
  function day(iso) { var p = iso.split("-"); return Date.UTC(+p[0], +p[1] - 1, +p[2]) / 864e5; }
  function iso(dayNum) { return new Date(dayNum * 864e5).toISOString().slice(0, 10); }
  function br(isoDate) { return isoDate ? isoDate.slice(8, 10) + "/" + isoDate.slice(5, 7) : ""; }
  function brFull(isoDate) { return isoDate ? br(isoDate) + "/" + isoDate.slice(0, 4) : ""; }
  function weekday(isoDate) { return new Date(day(isoDate) * 864e5).getUTCDay(); }
  function monthKey(isoDate) { return isoDate.slice(0, 7); }
  function monthLabel(key) { return MONTHS[+key.slice(5, 7) - 1] + "/" + key.slice(2, 4); }
  function monthsBetween(a, b) {
    var out = [], y = +a.slice(0, 4), m = +a.slice(5, 7), ey = +b.slice(0, 4), em = +b.slice(5, 7);
    while (y < ey || (y === ey && m <= em)) {
      out.push(y + "-" + (m < 10 ? "0" : "") + m);
      m += 1; if (m > 12) { m = 1; y += 1; }
    }
    return out;
  }
  /* Início do eixo: o primeiro mês com dado (sem meses vazios espremendo o gráfico), dentro do período. */
  function firstDataDay(dates, start, end) {
    var have = dates.filter(function (d) { return d >= start && d <= end; });
    if (!have.length) return start;
    var first = have.reduce(function (a, b) { return a < b ? a : b; }).slice(0, 7) + "-01";
    return first < start ? start : first;
  }
  function lastDay(key) { var y = +key.slice(0, 4), m = +key.slice(5, 7); return iso(Date.UTC(y, m, 0) / 864e5); }

  /* Divisão inteira arredondada "metade para o par", em centésimos (como Decimal.quantize no servidor). */
  function ratioCents(numr, den) {
    var q = Math.floor(numr / den), r = numr - q * den;
    if (2 * r > den || (2 * r === den && q % 2 !== 0)) q += 1;
    return q / 100;
  }
  /* Média de uma disciplina pela fórmula da escola, já arredondada a 2 casas como no servidor
     (services._apply_formula + _round, em Decimal): notas e pesos viram centésimos inteiros. */
  function average(vw, formula) {
    if (!vw.length) return null;
    var vc = vw.map(function (x) { return Math.round(x[0] * 100); });
    var wc = vw.map(function (x) { return Math.round((x[1] || 1) * 100); });
    var sum = function (a) { return a.reduce(function (p, q) { return p + q; }, 0); };
    if (formula === "ponderada") {
      var tw = sum(wc);
      return tw ? ratioCents(sum(vc.map(function (v, i) { return v * wc[i]; })), tw) : null;
    }
    if (formula === "melhor_nota") return Math.max.apply(null, vc) / 100;
    if (formula === "soma") return sum(vc) / 100;
    return ratioCents(sum(vc), vc.length);
  }
  /* Tendência: inclinação (pontos por mês) da reta de mínimos quadrados, como bi.trend. */
  function trend(points) {
    var months = {};
    points.forEach(function (p) { months[monthKey(p[0])] = 1; });
    if (points.length < 4 || Object.keys(months).length < 2) return { slope: null, label: "dados insuficientes" };
    var x0 = Math.min.apply(null, points.map(function (p) { return day(p[0]); }));
    var xs = points.map(function (p) { return (day(p[0]) - x0) / 30.44; });
    var ys = points.map(function (p) { return p[1]; });
    var mx = mean(xs), my = mean(ys), den = 0, numr = 0;
    xs.forEach(function (x, i) { den += (x - mx) * (x - mx); numr += (x - mx) * (ys[i] - my); });
    if (!den) return { slope: null, label: "dados insuficientes" };
    var slope = numr / den;
    return { slope: round(slope, 2), label: slope >= 0.3 ? "em alta" : slope <= -0.3 ? "em queda" : "estável" };
  }
  function band(v) { for (var i = 0; i < BANDS.length; i++) if (v >= BANDS[i][1] && v < BANDS[i][2]) return i; return BANDS.length - 1; }

  // ------------------------------------------------------------------ dica flutuante e marcas interativas
  var tipBox = h("div", { "class": "bx-tip", role: "status", hidden: true });
  root.appendChild(tipBox);
  function showTip(text, x, y) {
    tipBox.textContent = text;
    tipBox.hidden = false;
    var box = root.getBoundingClientRect();
    var left = Math.min(x - box.left + 12, root.clientWidth - tipBox.offsetWidth - 4);
    tipBox.style.left = Math.max(0, left) + "px";
    tipBox.style.top = (y - box.top + 14) + "px";
  }
  function hideTip() { tipBox.hidden = true; }
  /* Torna um nó clicável por mouse, toque e teclado, com dica. */
  function mark(node, label, onActivate, pressed) {
    node.classList.add("bx-mark");
    // O nome lido é a dica completa; os textos desenhados dentro da marca ficam só para os olhos.
    Array.prototype.forEach.call(node.querySelectorAll ? node.querySelectorAll("text") : [], function (t) {
      t.setAttribute("aria-hidden", "true");
    });
    attrs(node, { tabindex: "0", role: "button", "aria-label": label,
                  "aria-pressed": pressed === undefined ? null : String(!!pressed) });
    node.addEventListener("click", function (e) { hideTip(); onActivate(e); });
    node.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onActivate(e); }
    });
    node.addEventListener("mousemove", function (e) { showTip(label, e.clientX, e.clientY); });
    node.addEventListener("mouseleave", hideTip);
    node.addEventListener("focus", function () {
      var r = node.getBoundingClientRect(); showTip(label, r.left + r.width / 2, r.bottom);
    });
    node.addEventListener("blur", hideTip);
    return node;
  }
  function svgPoint(svgEl, e) {
    var pt = svgEl.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
    return pt.matrixTransform(svgEl.getScreenCTM().inverse());
  }
  /* Arrastar sobre a área do gráfico: retângulo de seleção (só eixo x, ou x e y). */
  function brush(svgEl, area, mode, onBrush) {
    var bg = s("rect", { x: area.x, y: area.y, width: area.w, height: area.h, "class": "bx-plot-bg" });
    var rect = null, start = null;
    bg.addEventListener("pointerdown", function (e) {
      start = svgPoint(svgEl, e);
      bg.setPointerCapture(e.pointerId);
      rect = s("rect", { "class": "bx-brush", x: start.x, y: mode === "x" ? area.y : start.y, width: 0,
                         height: mode === "x" ? area.h : 0 });
      svgEl.appendChild(rect);
    });
    bg.addEventListener("pointermove", function (e) {
      if (!start) return;
      var p = svgPoint(svgEl, e);
      var x = Math.max(area.x, Math.min(p.x, area.x + area.w)), y = Math.max(area.y, Math.min(p.y, area.y + area.h));
      attrs(rect, { x: Math.min(x, start.x), width: Math.abs(x - start.x) });
      if (mode !== "x") attrs(rect, { y: Math.min(y, start.y), height: Math.abs(y - start.y) });
    });
    function finish(e) {
      if (!start) return;
      var p = svgPoint(svgEl, e), s0 = start;
      start = null;
      if (rect) { rect.remove(); rect = null; }
      if (Math.abs(p.x - s0.x) < 6 && (mode === "x" || Math.abs(p.y - s0.y) < 6)) { onBrush(null); return; }
      onBrush({ x0: Math.min(p.x, s0.x), x1: Math.max(p.x, s0.x), y0: Math.min(p.y, s0.y), y1: Math.max(p.y, s0.y) });
    }
    bg.addEventListener("pointerup", finish);
    bg.addEventListener("pointercancel", function () { start = null; if (rect) { rect.remove(); rect = null; } });
    return bg;
  }

  // ------------------------------------------------------------------ gráficos
  /* Barras horizontais: [{label, value, max, ref, cls, selected, dim, tip, onClick, extra}] */
  function hbars(width, rows, opt) {
    opt = opt || {};
    var labelW = Math.min(170, Math.max(90, width * 0.32)), rowH = 28, top = 6, right = 46;
    var H = top + rows.length * rowH + 18, plotW = Math.max(40, width - labelW - right);
    var max = opt.max || Math.max.apply(null, rows.map(function (r) { return r.value || 0; }).concat([1]));
    var svgEl = s("svg", { viewBox: "0 0 " + width + " " + H, "class": "bx-chart", role: "group",
                           "aria-label": opt.aria || "" });
    (opt.digits === 0 && max < 4 ? [0, 1] : [0, 0.5, 1]).forEach(function (f) {
      var x = labelW + f * plotW;
      svgEl.appendChild(s("line", { x1: x, x2: x, y1: top, y2: H - 16, "class": "bx-grid-line" }));
      svgEl.appendChild(s("text", { x: x, y: H - 3, "text-anchor": "middle", "class": "bx-axis",
                                    text: num(f * max, opt.axisDigits || 0) + (opt.suffix || "") }));
    });
    rows.forEach(function (r, i) {
      var y = top + i * rowH;
      var g = s("g");
      g.appendChild(s("rect", { x: 0, y: y, width: width, height: rowH, "class": "bx-hit" }));
      var label = r.label.length > 24 ? r.label.slice(0, 23) + "…" : r.label;
      // Rótulo e valor ficam fora do grupo clicável (o nome lido é a dica completa) e não capturam o clique.
      var texts = [s("text", { x: labelW - 8, y: y + rowH / 2 + 4, "text-anchor": "end", "class": "bx-axis-strong bx-passive",
                               "aria-hidden": "true", text: label })];
      if (r.stack) {
        var x = labelW;
        r.stack.forEach(function (part) {
          var w = (part.value / max) * plotW;
          if (w > 0) g.appendChild(s("rect", { x: x, y: y + 6, width: w, height: rowH - 12, rx: 2,
                                               "class": "bx-bar " + (part.cls || "") }));
          x += w;
        });
      } else if (r.value !== null && r.value !== undefined) {
        g.appendChild(s("rect", { x: labelW, y: y + 6, width: Math.max(1, (Math.min(r.value, max) / max) * plotW),
                                  height: rowH - 12, rx: 3, "class": "bx-bar " + (r.cls || "") +
                                  (r.selected ? " is-selected" : "") }));
      }
      if (r.ref !== undefined && r.ref !== null) {
        var rx = labelW + (r.ref / max) * plotW;
        g.appendChild(s("line", { x1: rx, x2: rx, y1: y + 3, y2: y + rowH - 3, "class": "bx-ref" }));
      }
      if (r.mark2 !== undefined && r.mark2 !== null) {  // ◆ referência extra (média da turma nas mesmas avaliações)
        var mx = labelW + (Math.min(r.mark2, max) / max) * plotW, my = y + rowH / 2;
        g.appendChild(s("path", { d: "M" + mx + " " + (my - 6) + " l5 6 l-5 6 l-5 -6 z", "class": "bx-class-mark" }));
      }
      texts.push(s("text", { x: width - right + 6, y: y + rowH / 2 + 4, "class": "bx-value bx-passive", "aria-hidden": "true",
                             text: r.valueText !== undefined ? r.valueText : num(r.value, opt.digits === undefined ? 1 : opt.digits) }));
      if (r.dim) { g.classList.add("is-dim"); texts.forEach(function (t) { t.classList.add("is-dim"); }); }
      svgEl.appendChild(r.onClick ? mark(g, r.tip || r.label, r.onClick, r.selected) : g);
      texts.forEach(function (t) { svgEl.appendChild(t); });
    });
    return svgEl;
  }

  /* Colunas verticais (histograma): [{label, value, selected, dim, tip, onClick, cls}] */
  function columns(width, rows, opt) {
    opt = opt || {};
    var H = 170, left = 28, bottom = 22, top = 10, plotH = H - top - bottom, plotW = width - left - 6;
    var max = Math.max.apply(null, rows.map(function (r) { return r.value || 0; }).concat([1]));
    var colW = plotW / Math.max(rows.length, 1);
    var svgEl = s("svg", { viewBox: "0 0 " + width + " " + H, "class": "bx-chart", role: "group", "aria-label": opt.aria || "" });
    [0, 0.5, 1].forEach(function (f) {
      var y = top + plotH - f * plotH;
      svgEl.appendChild(s("line", { x1: left, x2: width - 6, y1: y, y2: y, "class": "bx-grid-line" }));
      svgEl.appendChild(s("text", { x: left - 4, y: y + 4, "text-anchor": "end", "class": "bx-axis", text: num(f * max, 0) }));
    });
    rows.forEach(function (r, i) {
      var x = left + i * colW, bh = (r.value / max) * plotH;
      var g = s("g");
      g.appendChild(s("rect", { x: x, y: top, width: colW, height: plotH, "class": "bx-hit" }));
      if (r.value) g.appendChild(s("rect", { x: x + colW * 0.15, y: top + plotH - bh, width: colW * 0.7, height: bh, rx: 3,
                                             "class": "bx-bar " + (r.cls || "") + (r.selected ? " is-selected" : "") }));
      var texts = [s("text", { x: x + colW / 2, y: H - 6, "text-anchor": "middle", "class": "bx-axis bx-passive",
                               "aria-hidden": "true", text: r.label })];
      if (r.value) texts.push(s("text", { x: x + colW / 2, y: top + plotH - bh - 4, "text-anchor": "middle",
                                          "class": "bx-value bx-passive", "aria-hidden": "true", text: num(r.value, 0) }));
      if (r.dim) g.classList.add("is-dim");
      svgEl.appendChild(r.onClick ? mark(g, r.tip || r.label, r.onClick, r.selected) : g);
      texts.forEach(function (t) { svgEl.appendChild(t); });
    });
    return svgEl;
  }

  /* Linha do tempo com pontos, linhas e arraste para escolher o intervalo.
     opt: {start, end, yMax, ref, points:[{d,v,cls,dim,tip}], lines:[{pts:[[d,v]], cls}], range:[from,to], onRange} */
  function timeline(width, opt) {
    var H = 210, left = 30, right = opt.y2 ? 34 : 10, top = 10, bottom = 24;
    var plotW = width - left - right, plotH = H - top - bottom;
    var d0 = day(opt.start), d1 = Math.max(day(opt.end), d0 + 1);
    var X = function (isoDate) { return left + (day(isoDate) - d0) / (d1 - d0) * plotW; };
    var Y = function (v) { return top + plotH - (v / opt.yMax) * plotH; };
    var Y2 = function (v) { return top + plotH - (v / 100) * plotH; };
    var svgEl = s("svg", { viewBox: "0 0 " + width + " " + H, "class": "bx-chart", role: "group", "aria-label": opt.aria || "" });
    [0, 0.5, 1].forEach(function (f) {
      var y = top + plotH - f * plotH;
      svgEl.appendChild(s("line", { x1: left, x2: left + plotW, y1: y, y2: y, "class": "bx-grid-line" }));
      svgEl.appendChild(s("text", { x: left - 4, y: y + 4, "text-anchor": "end", "class": "bx-axis", text: num(f * opt.yMax, 0) }));
      if (opt.y2) svgEl.appendChild(s("text", { x: left + plotW + 4, y: y + 4, "class": "bx-axis", text: num(f * 100, 0) + "%" }));
    });
    var months = monthsBetween(opt.start, opt.end);
    var step = Math.ceil(months.length / Math.max(1, Math.floor(plotW / 52)));
    months.forEach(function (m, i) {
      if (i % step) return;
      var x = X(m + "-01" < opt.start ? opt.start : m + "-01");
      svgEl.appendChild(s("text", { x: x, y: H - 6, "class": "bx-axis", text: monthLabel(m) }));
    });
    svgEl.appendChild(brush(svgEl, { x: left, y: top, w: plotW, h: plotH }, "x", function (b) {
      if (!b) { opt.onRange(null); return; }
      var a = iso(Math.round(d0 + (b.x0 - left) / plotW * (d1 - d0)));
      var z = iso(Math.round(d0 + (b.x1 - left) / plotW * (d1 - d0)));
      opt.onRange([a < opt.start ? opt.start : a, z > opt.end ? opt.end : z]);
    }));
    if (opt.range) {
      var rx0 = Math.max(left, X(opt.range[0])), rx1 = Math.min(left + plotW, X(opt.range[1]));
      svgEl.appendChild(s("rect", { x: rx0, y: top, width: Math.max(2, rx1 - rx0), height: plotH, "class": "bx-brush" }));
    }
    if (opt.ref !== undefined && opt.ref !== null) {
      svgEl.appendChild(s("line", { x1: left, x2: left + plotW, y1: Y(opt.ref), y2: Y(opt.ref), "class": "bx-ref" }));
      svgEl.appendChild(s("text", { x: left + plotW - 2, y: Y(opt.ref) - 4, "text-anchor": "end", "class": "bx-ref-label",
                                    text: opt.refLabel || "" }));
    }
    (opt.lines || []).forEach(function (ln) {
      var pts = ln.pts.filter(function (p) { return p[1] !== null; });
      if (pts.length < 2) return;
      var yf = ln.y2 ? Y2 : Y;
      var d = pts.map(function (p, i) { return (i ? "L" : "M") + X(p[0]).toFixed(1) + " " + yf(p[1]).toFixed(1); }).join(" ");
      svgEl.appendChild(s("path", { d: d, "class": "bx-line " + (ln.cls || "") }));
    });
    (opt.points || []).forEach(function (p) {
      var c = s("circle", { cx: X(p.d), cy: (p.y2 ? Y2 : Y)(p.v), r: p.r || 5,
                            "class": "bx-dot " + (p.cls || "") + (p.dim ? " is-dim" : "") });
      svgEl.appendChild(p.onClick ? mark(c, p.tip, p.onClick) : mark(c, p.tip, function () {}));
    });
    return svgEl;
  }

  /* Dispersão com quadrante de atenção e seleção por arraste. */
  function scatter(width, opt) {
    var H = 260, left = 36, right = 12, top = 12, bottom = 30;
    var plotW = width - left - right, plotH = H - top - bottom;
    // Eixo de frequência a partir de um pouco abaixo do menor valor (e da mínima): com 0 a 100%, a turma toda
    // ficava espremida no canto direito.
    var lowest = Math.min.apply(null, opt.points.map(function (p) { return p.x; }).concat([opt.minAtt]));
    var x0 = Math.max(0, Math.min(50, Math.floor((lowest - 5) / 10) * 10));
    var X = function (v) { return left + ((v - x0) / (100 - x0)) * plotW; };
    var Y = function (v) { return top + plotH - (v / 10) * plotH; };
    var svgEl = s("svg", { viewBox: "0 0 " + width + " " + H, "class": "bx-chart", role: "group", "aria-label": opt.aria || "" });
    svgEl.appendChild(s("rect", { x: left, y: Y(opt.passing), width: X(opt.minAtt) - left, height: top + plotH - Y(opt.passing),
                                  "class": "bx-quad" }));
    svgEl.appendChild(s("text", { x: left + 4, y: top + plotH - 6, "class": "bx-quad-label",
                                  text: "Atenção: frequência e média baixas" }));
    [0, 2, 4, 6, 8, 10].forEach(function (v) {
      svgEl.appendChild(s("line", { x1: left, x2: left + plotW, y1: Y(v), y2: Y(v), "class": "bx-grid-line" }));
      svgEl.appendChild(s("text", { x: left - 5, y: Y(v) + 4, "text-anchor": "end", "class": "bx-axis", text: v }));
    });
    var stepX = 100 - x0 <= 50 ? 10 : 25, ticks = [];
    for (var tv = x0; tv <= 100; tv += stepX) ticks.push(tv);
    ticks.forEach(function (v) {
      svgEl.appendChild(s("text", { x: X(v), y: H - 12, "text-anchor": "middle", "class": "bx-axis", text: v + "%" }));
    });
    svgEl.appendChild(s("text", { x: left + plotW, y: H - 1, "text-anchor": "end", "class": "bx-axis", text: "frequência →" }));
    svgEl.appendChild(s("line", { x1: X(opt.minAtt), x2: X(opt.minAtt), y1: top, y2: top + plotH, "class": "bx-ref" }));
    svgEl.appendChild(s("line", { x1: left, x2: left + plotW, y1: Y(opt.passing), y2: Y(opt.passing), "class": "bx-ref" }));
    svgEl.appendChild(brush(svgEl, { x: left, y: top, w: plotW, h: plotH }, "xy", function (b) {
      if (!b) { opt.onSelect(null); return; }
      var inside = opt.points.filter(function (p) {
        var x = X(p.x), y = Y(p.y); return x >= b.x0 && x <= b.x1 && y >= b.y0 && y <= b.y1;
      });
      opt.onSelect(inside.map(function (p) { return p.id; }));
    }));
    opt.points.forEach(function (p) {
      var c = s("circle", { cx: X(p.x), cy: Y(p.y), r: 6,
                            "class": "bx-dot " + (p.cls || "") + (p.selected ? " is-selected" : "") + (p.dim ? " is-dim" : "") });
      svgEl.appendChild(mark(c, p.tip, p.onClick, p.selected));
    });
    return svgEl;
  }

  /* Calendário de frequência: semanas em colunas, dias úteis em linhas. */
  function calendar(width, opt) {
    var first = day(opt.start), last = day(opt.end);
    first -= (new Date(first * 864e5).getUTCDay() + 6) % 7; // começa na segunda
    var weeks = Math.ceil((last - first + 1) / 7), rows = opt.weekend ? 7 : 5;
    var left = 34, top = 16, cell = Math.max(9, Math.min(18, (width - left - 4) / weeks));
    var W = Math.max(width, left + weeks * cell + 4), H = top + rows * cell + 6;
    var svgEl = s("svg", { viewBox: "0 0 " + W + " " + H, "class": "bx-chart", role: "group", "aria-label": opt.aria || "" });
    ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"].slice(0, rows).forEach(function (lab, i) {
      if (i % 2 === 0) svgEl.appendChild(s("text", { x: 0, y: top + i * cell + cell - 3, "class": "bx-axis", text: lab }));
    });
    var lastMonth = "";
    for (var w = 0; w < weeks; w++) {
      for (var r = 0; r < rows; r++) {
        var dn = first + w * 7 + r;
        if (dn < day(opt.start) || dn > last) continue;
        var isoDate = iso(dn), rec = opt.byDay[isoDate];
        if (r === 0 && monthKey(isoDate) !== lastMonth) {
          lastMonth = monthKey(isoDate);
          svgEl.appendChild(s("text", { x: left + w * cell, y: 11, "class": "bx-axis", text: monthLabel(lastMonth) }));
        }
        var st = rec ? (rec.st === "F" && rec.j ? "J" : rec.st) : "none";
        var cellEl = s("rect", { x: left + w * cell, y: top + r * cell, width: cell - 1, height: cell - 1, rx: 2,
                                 "class": "bx-day st-" + st + (opt.dim && opt.dim(isoDate) ? " is-dim" : "") });
        if (rec) mark(cellEl, brFull(isoDate) + " · " + opt.label(rec), function () {});
        svgEl.appendChild(cellEl);
      }
    }
    return svgEl;
  }

  function sparkline(values) {
    var pts = values.filter(function (v) { return v !== null; });
    if (pts.length < 2) return null;
    var max = Math.max.apply(null, pts), min = Math.min.apply(null, pts), W = 120, H = 26;
    var span = max - min || 1, i = 0, n = values.length - 1 || 1;
    var d = values.map(function (v, k) {
      if (v === null) return "";
      return (i++ ? "L" : "M") + (k / n * W).toFixed(1) + " " + (H - 3 - (v - min) / span * (H - 6)).toFixed(1);
    }).join(" ");
    return s("svg", { viewBox: "0 0 " + W + " " + H, "class": "bx-spark", "aria-hidden": "true",
                      preserveAspectRatio: "none" }, [s("path", { d: d })]);
  }

  function table(head, rows, opt) {
    opt = opt || {};
    var thead = h("tr", null, head.map(function (c, i) {
      var th = h("th", { scope: "col", "class": c.num ? "num" : null });
      if (opt.onSort) {
        th.appendChild(h("button", { type: "button", "class": "bx-sort", text: c.label + (opt.sortKey === i ? (opt.sortDir > 0 ? " ▲" : " ▼") : ""),
                                     on: { click: function () { opt.onSort(i); } } }));
        if (opt.sortKey === i) th.setAttribute("aria-sort", opt.sortDir > 0 ? "ascending" : "descending");
      } else th.textContent = c.label;
      return th;
    }));
    var body = h("tbody", null, rows.map(function (r) {
      var tr = h("tr", { "class": r.cls || null }, r.cells.map(function (c, i) {
        var tdAttrs = { "class": (head[i].num ? "num " : "") + (c && c.cls ? c.cls : "") };
        if (c && c.attrs) Object.keys(c.attrs).forEach(function (k) { tdAttrs[k] = c.attrs[k]; });
        return h("td", tdAttrs, c && c.node ? c.node : (c && c.text !== undefined ? c.text : c));
      }));
      if (r.onClick) {
        // O teclado e o leitor de tela usam o botão da primeira célula; o mouse pode clicar em qualquer ponto.
        tr.classList.add("bx-row");
        var first = tr.firstChild;
        var btn = h("button", { type: "button", "class": "bx-rowbtn", "aria-pressed": String(!!r.selected),
                                "aria-label": (r.label || first.textContent) + (r.selected ? " (selecionado)" : "") });
        while (first.firstChild) btn.appendChild(first.firstChild);
        first.appendChild(btn);
        btn.addEventListener("click", function (e) { e.stopPropagation(); r.onClick(e); });
        tr.addEventListener("click", function (e) { if (e.target.closest("a, button")) return; r.onClick(e); });
      }
      return tr;
    }));
    return h("div", { "class": "bx-table-wrap" }, [h("table", { "class": "bx-table " + (opt.cls || "") },
                                                      [h("thead", null, thead), body])]);
  }

  // ------------------------------------------------------------------ moldura do painel
  var app = { data: null, state: null, tableMode: {}, render: null, focus: null };

  function card(title, hint, size, draw, tabular, opts) {
    var key = (opts && opts.key) || title;
    var focused = app.focus === key;
    var body = h("div");
    var tools = h("div", { "class": "bx-card-tools" });
    if (tabular) {
      tools.appendChild(h("button", { type: "button", "class": "bx-tool", "aria-pressed": String(!!app.tableMode[key]),
                                      text: "Tabela", on: { click: function () { app.tableMode[key] = !app.tableMode[key]; app.render(); } } }));
    }
    if (!(opts && opts.noFocus)) {
      tools.appendChild(h("button", { type: "button", "class": "bx-tool", "aria-pressed": String(focused),
                                      title: focused ? "Voltar ao painel (Esc)" : "Ver este visual sozinho, em largura total",
                                      text: focused ? "Voltar" : "Ampliar",
                                      on: { click: function () { app.focus = focused ? null : key; app.render(); window.scrollTo(0, root.offsetTop); } } }));
    }
    var c = h("section", { "class": "bx-card " + (focused ? "is-focus" : (size || "")) }, [
      h("div", { "class": "bx-card-head" }, [h("h3", { text: title }), tools]),
      hint ? h("p", { "class": "bx-card-hint", text: hint }) : null, body]);
    return { node: c, key: key, fill: function () {
      var width = Math.max(260, body.clientWidth || 600);
      var out = app.tableMode[key] && tabular ? tabular() : draw(width);
      add(body, out || h("p", { "class": "bx-empty", text: "Sem dados neste recorte." }));
    } };
  }

  function kpi(label, value, note, cls, spark, change) {
    return h("div", { "class": "bx-kpi " + (cls || "") }, [
      h("span", { "class": "bx-kpi-label", text: label }),
      h("span", { "class": "bx-kpi-value", text: value }),
      change ? h("span", { "class": "bx-delta " + change.cls, text: change.text }) : null,
      note ? h("span", { "class": "bx-kpi-note", text: note }) : null,
      spark || null]);
  }

  /* Põe na tela os cartões: todos, ou só o ampliado (modo foco). */
  function place(grid, cards) {
    if (app.focus && !cards.some(function (c) { return c.key === app.focus; })) app.focus = null;
    var shown = app.focus ? cards.filter(function (c) { return c.key === app.focus; }) : cards;
    shown.forEach(function (c) { grid.appendChild(c.node); });
    shown.forEach(function (c) { c.fill(); });
  }

  function chip(label, pressed, onClick, title) {
    return h("button", { type: "button", "class": "bx-chip", "aria-pressed": String(!!pressed), title: title || null,
                         text: label, on: { click: onClick } });
  }

  // Estado no endereço (#bi:f=...&t=...&s=1,2&e=3,4&b=2&w=1&o=1)
  function readHash() {
    var st = {};
    if (location.hash.indexOf("#bi:") !== 0) return st;
    location.hash.slice(4).split("&").forEach(function (kv) {
      var p = kv.split("="), v = decodeURIComponent(p[1] || "");
      if (!v) return;
      if (p[0] === "f" || p[0] === "t") st[p[0] === "f" ? "from" : "to"] = /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
      else if (p[0] === "s" || p[0] === "e") st[p[0] === "s" ? "subjects" : "students"] = v.split(",").map(Number).filter(isFinite);
      else if (p[0] === "b" || p[0] === "w") st[p[0] === "b" ? "band" : "weekday"] = +v;
      else if (p[0] === "o") st.follow = v === "1";
    });
    return st;
  }
  function writeHash(st) {
    var parts = [];
    if (st.from) parts.push("f=" + st.from);
    if (st.to) parts.push("t=" + st.to);
    if (st.subjects.length) parts.push("s=" + st.subjects.join(","));
    if (st.students && st.students.length) parts.push("e=" + st.students.join(","));
    if (st.band !== null) parts.push("b=" + st.band);
    if (st.weekday !== null) parts.push("w=" + st.weekday);
    if (st.follow) parts.push("o=1");
    var url = location.pathname + location.search + (parts.length ? "#bi:" + parts.join("&") : "");
    try { history.replaceState(null, "", url); } catch (e) { /* sem histórico: segue sem guardar */ }
  }

  function toggle(list, value) {
    var i = list.indexOf(value);
    if (i === -1) list.push(value); else list.splice(i, 1);
    return list;
  }

  // ------------------------------------------------------------------ montagem comum
  function frame(data, title, subtitle) {
    root.textContent = "";
    root.appendChild(tipBox);
    var head = h("div", { "class": "bx-head" }, [
      h("div", null, [h("h2", { text: title }), h("p", { "class": "bx-sub", text: subtitle })]),
      h("div", { "class": "bx-switch" }, [
        h("button", { type: "button", "class": "btn btn-sm btn-outline-secondary", text: "Imprimir esta visão",
                      on: { click: printView } }),
        h("a", { "class": "btn btn-sm btn-outline-secondary", href: "#relatorio-detalhado", text: "Ir para o relatório detalhado" })])]);
    var slicers = h("div", { "class": "bx-slicers", role: "group", "aria-label": "Recortes do painel" });
    var filters = h("div", { "class": "bx-filters", "aria-live": "polite" });
    var selection = h("div", { "class": "bx-selection", hidden: true, "aria-live": "polite" });
    var kpis = h("div", { "class": "bx-kpis" });
    var grid = h("div", { "class": "bx-grid" });
    add(root, [head, slicers, filters, selection, kpis, grid]);
    return { slicers: slicers, filters: filters, selection: selection, kpis: kpis, grid: grid };
  }

  function periodSlicer(container, data, st, rerender) {
    var meta = data.meta;
    var row = h("div", { "class": "bx-slicer" }, [h("span", { "class": "bx-slicer-label", text: "Período" })]);
    var any = !st.from && !st.to;
    row.appendChild(chip("Todo o período", any, function () { st.from = st.to = null; rerender(); }));
    var options = meta.terms.length ? meta.terms.map(function (t) { return { label: t.name, from: t.start, to: t.end }; })
      : monthsBetween(meta.period.start, meta.period.end).map(function (m) {
        var from = m + "-01" < meta.period.start ? meta.period.start : m + "-01";
        var to = lastDay(m) > meta.period.end ? meta.period.end : lastDay(m);
        return { label: monthLabel(m), from: from, to: to };
      });
    if (options.length > 14) options = options.slice(-14);
    options.forEach(function (o) {
      var on = st.from === o.from && st.to === o.to;
      row.appendChild(chip(o.label, on, function () {
        if (on) { st.from = st.to = null; } else { st.from = o.from; st.to = o.to; }
        rerender();
      }, br(o.from) + " a " + br(o.to)));
    });
    container.appendChild(row);
  }

  function subjectSlicer(container, data, st, rerender) {
    if (!data.subjects.length) return;
    var row = h("div", { "class": "bx-slicer" }, [h("span", { "class": "bx-slicer-label", text: "Disciplinas" })]);
    row.appendChild(chip("Todas", !st.subjects.length, function () { st.subjects = []; rerender(); }));
    data.subjects.forEach(function (sub) {
      row.appendChild(chip(sub.name, st.subjects.indexOf(sub.id) !== -1, function () { toggle(st.subjects, sub.id); rerender(); }));
    });
    container.appendChild(row);
  }

  function activeFilters(container, items, clearAll) {
    items.forEach(function (it) {
      container.appendChild(h("button", { type: "button", "class": "bx-filter", "aria-label": "Remover filtro: " + it.label,
                                          text: it.label, on: { click: it.remove } }));
    });
    if (items.length) container.appendChild(h("button", { type: "button", "class": "bx-clear", text: "Limpar todos os filtros",
                                                           on: { click: clearAll } }));
  }

  function inRange(st, d) { return (!st.from || d >= st.from) && (!st.to || d <= st.to); }

  /* Imprime só o painel interativo, no recorte atual (o resto da página some durante a impressão). */
  function printView() {
    var hidden = [], node = root;
    while (node && node.parentElement && node !== document.body) {
      Array.prototype.forEach.call(node.parentElement.children, function (sib) {
        if (sib !== node && !sib.classList.contains("bx-print-hide")) { sib.classList.add("bx-print-hide"); hidden.push(sib); }
      });
      node = node.parentElement;
    }
    var done = false;
    var restore = function () {
      if (done) return;
      done = true;
      hidden.forEach(function (n) { n.classList.remove("bx-print-hide"); });
      window.removeEventListener("afterprint", restore);
    };
    window.addEventListener("afterprint", restore);
    window.print();
    // Navegador que não avisa o fim da impressão: devolve a página mesmo assim.
    setTimeout(restore, 1500);
  }

  function plural(n, one, many) { return n + " " + (n === 1 ? one : many); }
  function listNames(names, max) {
    var shown = names.slice(0, max || 4);
    var text = shown.length > 1 ? shown.slice(0, -1).join(", ") + " e " + shown[shown.length - 1] : shown[0] || "";
    return names.length > shown.length ? text + " e mais " + (names.length - shown.length) : text;
  }

  /* Janela anterior equivalente: o bimestre anterior, o mês anterior ou o mesmo número de dias logo antes. */
  function previousWindow(st, meta) {
    if (!st.from && !st.to) return null;
    var from = st.from || meta.period.start, to = st.to || meta.period.end, terms = meta.terms || [];
    for (var i = 0; i < terms.length; i++) {
      if (terms[i].start === from && terms[i].end === to) {
        return i ? { from: terms[i - 1].start, to: terms[i - 1].end, label: terms[i - 1].name } : null;
      }
    }
    var pf, pt, label;
    if (from.slice(8) === "01" && to === lastDay(monthKey(from))) {
      var y = +from.slice(0, 4), m = +from.slice(5, 7) - 1;
      if (m === 0) { m = 12; y -= 1; }
      var key = y + "-" + (m < 10 ? "0" : "") + m;
      pf = key + "-01"; pt = lastDay(key); label = monthLabel(key);
    } else {
      var len = day(to) - day(from) + 1;
      pf = iso(day(from) - len); pt = iso(day(from) - 1); label = br(pf) + " a " + br(pt);
    }
    if (pt < meta.period.start) return null;
    if (pf < meta.period.start) pf = meta.period.start;
    return { from: pf, to: pt, label: label };
  }
  /* Variação contra a janela anterior, para o cartão de indicador. */
  function change(now, before, digits, unit, prev) {
    if (!prev || now === null || before === null || now === undefined || before === undefined) return null;
    var d = round(now - before, digits);
    return { text: (d > 0 ? "▲ +" : d < 0 ? "▼ −" : "= ") + num(Math.abs(d), digits) + unit + " vs " + prev.label,
             cls: d > 0 ? "is-up" : d < 0 ? "is-down" : "" };
  }

  /* Leitura rápida: frases geradas por regras, cada uma com uma ação opcional. */
  function narrative(items) {
    if (!items.length) return h("p", { "class": "bx-empty", text: "Nenhum ponto de atenção neste recorte." });
    return h("ul", { "class": "bx-narrative" }, items.map(function (it) {
      return h("li", { "class": it.tone ? "is-" + it.tone : null }, [it.text,
        it.action ? h("button", { type: "button", "class": "bx-action", text: it.action.label, on: { click: it.action.run } }) : null]);
    }));
  }

  /* Mapa de calor disciplina × mês. value(idDisciplina, mês) -> {v, n}; onPick(id, mês) filtra os dois. */
  function heatmap(subjects, months, value, isOn, onPick) {
    if (!subjects.length || !months.length) return null;
    var head = [{ label: "Disciplina" }].concat(months.map(function (m) { return { label: monthLabel(m), num: true }; }));
    return table(head, subjects.map(function (x) {
      return { cells: [x.name].concat(months.map(function (m) {
        var c = value(x.id, m);
        if (!c || c.v === null) return { text: "—", cls: "bx-cell" };
        var heat = c.v < x.passing ? "bx-heat-0" : c.v < x.passing + 1 ? "bx-heat-1" : c.v < 8.5 ? "bx-heat-2" : "bx-heat-3";
        var on = isOn(x.id, m);
        return { cls: "bx-cell " + heat + (on ? " is-picked" : ""),
                 node: h("button", { type: "button", "class": "bx-heatbtn", "aria-pressed": String(on),
                                     title: x.name + " em " + monthLabel(m) + ": média " + num(c.v, 1) + " em " + plural(c.n, "nota", "notas"),
                                     "aria-label": x.name + " em " + monthLabel(m) + ": média " + num(c.v, 1) + " em " + plural(c.n, "nota", "notas"),
                                     text: num(c.v, 1), on: { click: function () { onPick(x.id, m); } } }) };
      })) };
    }), { cls: "bx-matrix bx-heatmap" });
  }
  function monthWindow(m, meta) {
    var from = m + "-01" < meta.period.start ? meta.period.start : m + "-01";
    var to = lastDay(m) > meta.period.end ? meta.period.end : lastDay(m);
    return { from: from, to: to };
  }
  function pickSubjectMonth(st, meta, sid, m) {
    var w = monthWindow(m, meta);
    if (st.subjects.length === 1 && st.subjects[0] === sid && st.from === w.from && st.to === w.to) {
      st.subjects = []; st.from = st.to = null;
    } else { st.subjects = [sid]; st.from = w.from; st.to = w.to; }
  }

  // ================================================================== estudante
  function studentApp(data) {
    var meta = data.meta, rules = meta.rules, names = {};
    data.subjects.forEach(function (x) { names[x.id] = x.name; });
    var G = data.grades.map(function (r) { return { d: r[0], s: r[1], v: r[2], w: r[3], t: r[4], k: r[5], cm: r[6] }; });
    var A = data.attendance.map(function (r) { return { d: r[0], st: r[1], j: r[2] }; });
    var T = data.activities.map(function (r) { return { d: r[0], s: r[1], st: r[2], t: r[3] }; });
    var hs = readHash();
    var st = { from: hs.from || null, to: hs.to || null, subjects: hs.subjects || [], band: isFinite(hs.band) ? hs.band : null,
               weekday: isFinite(hs.weekday) ? hs.weekday : null, sort: { key: 0, dir: -1 } };
    function rule(sid) { return rules[String(sid)] || { formula: "aritmetica", passing: 6 }; }
    function bySubject(grades) {
      var acc = {};
      grades.forEach(function (g) { (acc[g.s] = acc[g.s] || []).push([g.v, g.w]); });
      return Object.keys(acc).map(function (sid) {
        var r = rule(sid), avg = average(acc[sid], r.formula);
        return { id: +sid, name: names[sid] || "?", avg: avg, passing: r.passing, n: acc[sid].length };
      }).sort(function (a, b) { return a.name.localeCompare(b.name, "pt-BR"); });
    }
    function overall(rows) { var v = rows.filter(function (r) { return r.avg !== null; }).map(function (r) { return r.avg; }); return v.length ? round(mean(v), 2) : null; }
    var ATT = { P: "presente", A: "atraso", F: "falta" };
    var ACT = { E: "entregue no prazo", T: "entregue com atraso", N: "não entregue", S: "sem registro", O: "em aberto" };

    function render() {
      var subjOk = function (sid) { return !st.subjects.length || st.subjects.indexOf(sid) !== -1; };
      var gRange = G.filter(function (g) { return inRange(st, g.d); });
      var gSel = gRange.filter(function (g) { return subjOk(g.s); });
      var gBand = gSel.filter(function (g) { return st.band === null || band(g.v) === st.band; });
      var aRange = A.filter(function (a) { return inRange(st, a.d); });
      var aSel = aRange.filter(function (a) { return st.weekday === null || weekday(a.d) === st.weekday; });
      var tSel = T.filter(function (t) { return inRange(st, t.d) && subjOk(t.s); });
      var subjRows = bySubject(gSel), allSubj = bySubject(gRange);
      var ov = overall(subjRows);
      var present = aSel.filter(function (a) { return a.st !== "F"; }).length;
      var absent = aSel.length - present, justified = aSel.filter(function (a) { return a.st === "F" && a.j; }).length;
      var freq = pct(present, aSel.length);
      var delivered = tSel.filter(function (t) { return t.st === "E" || t.st === "T"; }).length;
      var registered = delivered + tSel.filter(function (t) { return t.st === "N"; }).length;
      var noRecord = tSel.filter(function (t) { return t.st === "S"; }).length;
      var tr = trend(gSel.map(function (g) { return [g.d, g.v]; }));
      var below = subjRows.filter(function (r) { return r.avg !== null && r.avg < r.passing; });
      var months = monthsBetween(st.from || firstDataDay(G.map(function (g) { return g.d; }).concat(A.map(function (a) { return a.d; })),
                                                       meta.period.start, meta.period.end), st.to || meta.period.end);
      var monthGrades = months.map(function (m) {
        var v = gSel.filter(function (g) { return monthKey(g.d) === m; }).map(function (g) { return g.v; });
        return v.length ? round(mean(v), 2) : null;
      });
      var monthFreq = months.map(function (m) {
        var r = aSel.filter(function (a) { return monthKey(a.d) === m; });
        return r.length ? pct(r.filter(function (a) { return a.st !== "F"; }).length, r.length) : null;
      });

      var f = frame(data, "Painel interativo — " + meta.student.name,
                    (meta.student.class ? meta.student.class + " · " : "") + meta.period.label +
                    ". Clique nas barras, arraste na linha do tempo e use os recortes: tudo se atualiza junto.");
      periodSlicer(f.slicers, data, st, update);
      subjectSlicer(f.slicers, data, st, update);
      var active = [];
      if (st.from || st.to) active.push({ label: "Datas: " + br(st.from || meta.period.start) + " a " + br(st.to || meta.period.end),
                                          remove: function () { st.from = st.to = null; update(); } });
      st.subjects.forEach(function (sid) { active.push({ label: names[sid] || "Disciplina", remove: function () { toggle(st.subjects, sid); update(); } }); });
      if (st.band !== null) active.push({ label: "Notas de " + BANDS[st.band][0], remove: function () { st.band = null; update(); } });
      if (st.weekday !== null) active.push({ label: "Frequência às " + WEEKDAYS[st.weekday].toLowerCase() + "s",
                                             remove: function () { st.weekday = null; update(); } });
      activeFilters(f.filters, active, function () { st.from = st.to = null; st.subjects = []; st.band = st.weekday = null; update(); });

      // Nota mínima de referência: a das disciplinas, quando todas usam a mesma; senão 6.
      var passings = allSubj.map(function (r) { return r.passing; });
      var passingRef = passings.length && passings.every(function (p) { return p === passings[0]; }) ? passings[0] : 6;
      var delivery = registered ? pct(delivered, registered) : null;
      // Mesmos indicadores na janela anterior (bimestre, mês ou mesmo número de dias), com os mesmos recortes.
      var prev = previousWindow(st, meta), before = null;
      if (prev) {
        var pg = G.filter(function (g) { return inRange(prev, g.d) && subjOk(g.s); });
        var pa = A.filter(function (a) { return inRange(prev, a.d) && (st.weekday === null || weekday(a.d) === st.weekday); });
        var pt = T.filter(function (t) { return inRange(prev, t.d) && subjOk(t.s); });
        var pd = pt.filter(function (t) { return t.st === "E" || t.st === "T"; }).length;
        var pr = pd + pt.filter(function (t) { return t.st === "N"; }).length;
        before = { ov: overall(bySubject(pg)), freq: pct(pa.filter(function (a) { return a.st !== "F"; }).length, pa.length),
                   delivery: pr ? pct(pd, pr) : null };
      }
      add(f.kpis, [
        kpi("Média geral", num(ov, 1), gSel.length + " nota(s) em " + subjRows.length + " disciplina(s)",
            ov !== null && ov < passingRef ? "is-alert" : "", sparkline(monthGrades), before && change(ov, before.ov, 1, "", prev)),
        kpi("Frequência", freq === null ? "—" : num(freq, 1) + "%",
            absent + " falta(s)" + (justified ? ", " + justified + " justificada(s)" : "") + " em " + aSel.length + " registro(s)",
            freq !== null && freq < meta.min_attendance ? "is-alert" : "", sparkline(monthFreq),
            before && change(freq, before.freq, 1, " p.p.", prev)),
        kpi("Entrega de atividades", registered ? num(delivery, 1) + "%" : "—",
            delivered + " de " + registered + " com registro" + (noRecord ? " · " + noRecord + " sem registro" : ""), "", null,
            before && change(delivery, before.delivery, 1, " p.p.", prev)),
        kpi("Tendência das notas", tr.slope === null ? "—" : (tr.slope > 0 ? "+" : "") + num(tr.slope, 2),
            tr.slope === null ? "precisa de 4 notas em 2 meses" : "pontos por mês · " + tr.label,
            tr.slope !== null && tr.slope <= -0.3 ? "is-alert" : tr.slope >= 0.3 ? "is-good" : ""),
        kpi("Disciplinas abaixo", subjRows.length ? String(below.length) : "—",
            below.length ? below.map(function (b) { return b.name; }).slice(0, 3).join(", ") : "nenhuma abaixo da nota mínima",
            below.length ? "is-alert" : "")]);

      // Comparação com a turma nas MESMAS avaliações (só a equipe recebe a média da turma, e só com 5+ notas).
      var vsClass = {};
      if (meta.class_comparison) {
        gRange.forEach(function (g) {
          if (g.cm === null) return;
          var c = vsClass[g.s] = vsClass[g.s] || { cm: [], diff: [] };
          c.cm.push(g.cm); c.diff.push(g.v - g.cm);
        });
      }

      // ---- leitura rápida (regras transparentes sobre os números deste recorte)
      var notes = [];
      if (ov !== null) {
        if (below.length) {
          notes.push({ tone: "alert", text: "Média geral " + num(ov, 1) + ", abaixo da mínima em " +
            listNames(below.map(function (b) { return b.name + " (" + num(b.avg, 1) + ")"; })) + ". " });
        } else {
          var best = subjRows.filter(function (r) { return r.avg !== null; }).sort(function (a, c) { return c.avg - a.avg; })[0];
          notes.push({ tone: "good", text: "Média geral " + num(ov, 1) + ", acima da mínima " +
            (subjRows.length === 1 ? "na única disciplina com notas" : "em todas as " + subjRows.length + " disciplinas") +
            (best && subjRows.length > 1 ? "; a mais alta é " + best.name + " (" + num(best.avg, 1) + ")." : ".") });
        }
      }
      if (tr.slope !== null && Math.abs(tr.slope) >= 0.3) {
        notes.push({ tone: tr.slope < 0 ? "alert" : "good", text: "Notas " + tr.label + ": " + (tr.slope > 0 ? "+" : "−") +
          num(Math.abs(tr.slope), 2) + " ponto por mês no recorte (reta de tendência sobre " + plural(gSel.length, "nota", "notas") + ")." });
      }
      if (prev && before && ov !== null && before.ov !== null && Math.abs(ov - before.ov) >= 0.5) {
        notes.push({ tone: ov < before.ov ? "alert" : "good", text: "Em relação a " + prev.label + ", a média " +
          (ov < before.ov ? "caiu" : "subiu") + " de " + num(before.ov, 1) + " para " + num(ov, 1) + "." });
      }
      if (freq !== null && freq < meta.min_attendance) {
        notes.push({ tone: "alert", text: "Frequência de " + num(freq, 1) + "%, abaixo do mínimo de " + num(meta.min_attendance, 0) + "%." });
      }
      var run = { n: 0, best: 0, start: null, bStart: null, bEnd: null };
      aSel.forEach(function (a) {
        if (a.st === "F") {
          if (!run.n) run.start = a.d;
          run.n += 1;
          if (run.n > run.best) { run.best = run.n; run.bStart = run.start; run.bEnd = a.d; }
        } else run.n = 0;
      });
      if (run.best >= 2) {
        notes.push({ tone: "alert", text: run.best + " faltas seguidas, de " + br(run.bStart) + " a " + br(run.bEnd) + " (maior sequência no recorte)." });
      }
      if (absent >= 3 && st.weekday === null) {
        var byWd = {};
        aRange.forEach(function (a) { if (a.st === "F") byWd[weekday(a.d)] = (byWd[weekday(a.d)] || 0) + 1; });
        var topWd = Object.keys(byWd).sort(function (a, c) { return byWd[c] - byWd[a]; })[0];
        if (topWd !== undefined && byWd[topWd] / absent >= 0.5 && byWd[topWd] >= 2) {
          notes.push({ tone: "alert", text: byWd[topWd] + " das " + absent + " faltas foram às " + WEEKDAYS[topWd].toLowerCase() + "s. ",
                       action: { label: "Ver só as " + WEEKDAYS[topWd].toLowerCase() + "s", run: function () { st.weekday = +topWd; update(); } } });
        }
      }
      if (noRecord) notes.push({ tone: "alert", text: plural(noRecord, "atividade", "atividades") + " com prazo vencido e sem registro de entrega." });
      if (delivery !== null && registered >= 3 && delivery < 60) {
        notes.push({ tone: "alert", text: "Entrega de atividades em " + num(delivery, 0) + "% (" + delivered + " de " + registered + " com registro)." });
      }
      Object.keys(vsClass).forEach(function (sid) {
        var d = mean(vsClass[sid].diff);
        if (vsClass[sid].diff.length >= 2 && Math.abs(d) >= 1 && subjOk(+sid)) {
          notes.push({ tone: d < 0 ? "alert" : "good", text: "Em " + (names[sid] || "?") + ", as notas ficaram em média " + num(Math.abs(d), 1) +
            (d < 0 ? " abaixo" : " acima") + " da turma nas mesmas avaliações (" + plural(vsClass[sid].diff.length, "avaliação", "avaliações") + ")." });
        }
      });

      var cards = [];
      cards.push(card("Leitura rápida", "Frases geradas por regras a partir dos números deste recorte. Não é previsão: é um resumo para orientar a conversa.", "",
        function () { return narrative(notes); }, null, { noFocus: true }));
      cards.push(card("Média por disciplina", "Clique para filtrar o painel pela disciplina. Tracejado: nota mínima" +
                      (meta.class_comparison ? " · ◆ média da turma nas mesmas avaliações." : "."), "w-6",
        function (w) {
          if (!allSubj.length) return null;
          return hbars(w, allSubj.map(function (r) {
            var on = st.subjects.indexOf(r.id) !== -1, cmp = vsClass[r.id];
            var cm = cmp ? mean(cmp.cm) : null;
            return { label: r.name, value: r.avg, ref: r.passing, mark2: cm, cls: r.avg !== null && r.avg < r.passing ? "is-below" : "",
                     selected: on, dim: st.subjects.length && !on,
                     tip: r.name + ": média " + num(r.avg, 1) + " (" + r.n + " nota(s); mínima " + num(r.passing, 1) + ")" +
                          (cm !== null ? "; turma nas mesmas avaliações: " + num(cm, 1) : ""),
                     onClick: function () { toggle(st.subjects, r.id); update(); } };
          }), { max: 10, aria: "Média por disciplina" });
        },
        function () {
          return table([{ label: "Disciplina" }, { label: "Média", num: true }, { label: "Mínima", num: true }, { label: "Notas", num: true }],
            allSubj.map(function (r) { return { cells: [r.name, num(r.avg, 1), num(r.passing, 1), r.n] }; }));
        }));
      cards.push(card("Notas ao longo do tempo", "Cada ponto é uma nota. Arraste sobre o gráfico para escolher um intervalo de datas; clique sem arrastar para desfazer.", "w-6",
        function (w) {
          var gSubj = G.filter(function (g) { return subjOk(g.s); });
          if (!gSubj.length) return null;
          var pts = gSubj.map(function (g) {
            var outside = !inRange(st, g.d) || (st.band !== null && band(g.v) !== st.band);
            return { d: g.d, v: g.v, cls: g.v < rule(g.s).passing ? "is-below" : "", dim: outside,
                     tip: brFull(g.d) + " · " + (names[g.s] || "") + " · " + g.t + ": " + num(g.v, 1) +
                          (g.cm !== null ? " (turma: " + num(g.cm, 1) + ")" : "") };
          });
          var cmPts = meta.class_comparison ? gSubj.filter(function (g) { return g.cm !== null; }).map(function (g) {
            return { d: g.d, v: g.cm, r: 3, cls: "is-alt", dim: !inRange(st, g.d), tip: brFull(g.d) + " · média da turma em " + g.t + ": " + num(g.cm, 1) };
          }) : [];
          var allMonths = monthsBetween(firstDataDay(gSubj.map(function (g) { return g.d; }), meta.period.start, meta.period.end), meta.period.end);
          var line = allMonths.map(function (m) {
            var v = gSubj.filter(function (g) { return monthKey(g.d) === m; }).map(function (g) { return g.v; });
            return [m + "-15" > meta.period.end ? meta.period.end : (m + "-15" < meta.period.start ? meta.period.start : m + "-15"), v.length ? mean(v) : null];
          });
          var axisStart = firstDataDay(gSubj.map(function (g) { return g.d; }), meta.period.start, meta.period.end);
          return timeline(w, { start: axisStart, end: meta.period.end, yMax: 10, ref: passingRef, refLabel: "mínima",
                               points: cmPts.concat(pts), lines: [{ pts: line.map(function (p) { return [p[0] < axisStart ? axisStart : p[0], p[1]]; }) }],
                               range: st.from || st.to ? [st.from || meta.period.start, st.to || meta.period.end] : null,
                               aria: "Notas ao longo do tempo",
                               onRange: function (r) { if (r) { st.from = r[0]; st.to = r[1]; } else { st.from = st.to = null; } update(); } });
        },
        function () {
          return table([{ label: "Mês" }, { label: "Média das notas", num: true }, { label: "Frequência", num: true }],
            months.map(function (m, i) { return { cells: [monthLabel(m), num(monthGrades[i], 1), monthFreq[i] === null ? "—" : num(monthFreq[i], 1) + "%"] }; }));
        }));
      cards.push(card("Distribuição das notas", "Clique numa faixa para ver só essas notas na tabela e na linha do tempo.", "w-4",
        function (w) {
          if (!gSel.length) return null;
          return columns(w, BANDS.map(function (b, i) {
            var n = gSel.filter(function (g) { return band(g.v) === i; }).length;
            return { label: b[0], value: n, cls: i < 3 ? "is-below" : "", selected: st.band === i, dim: st.band !== null && st.band !== i,
                     tip: n + " nota(s) entre " + b[0], onClick: function () { st.band = st.band === i ? null : i; update(); } };
          }), { aria: "Distribuição das notas por faixa" });
        }, null));
      cards.push(card("Frequência dia a dia", "Verde: presente · amarelo: atraso · vermelho: falta · azul: falta justificada.", "w-8",
        function (w) {
          if (!aRange.length) return null;
          var byDay = {};
          aRange.forEach(function (a) { byDay[a.d] = a; });
          var wrap = h("div");
          var calStart = st.from || firstDataDay(aRange.map(function (a) { return a.d; }), meta.period.start, meta.period.end);
          wrap.appendChild(calendar(w, { start: calStart, end: st.to || meta.period.end, byDay: byDay,
                                         weekend: aRange.some(function (a) { var d = weekday(a.d); return d === 0 || d === 6; }),
                                         dim: st.weekday === null ? null : function (d) { return weekday(d) !== st.weekday; },
                                         label: function (r) { return ATT[r.st] + (r.st === "F" && r.j ? " (justificada)" : ""); },
                                         aria: "Calendário de frequência" }));
          wrap.appendChild(h("div", { "class": "bx-legend" }, [h("span", { "class": "lg-P", text: "presente" }), h("span", { "class": "lg-A", text: "atraso" }),
                                                               h("span", { "class": "lg-F", text: "falta" }), h("span", { "class": "lg-J", text: "justificada" }),
                                                               h("span", { text: "sem registro" })]));
          return wrap;
        },
        function () {
          return table([{ label: "Data" }, { label: "Situação" }],
            aSel.slice().reverse().map(function (a) { return { cells: [brFull(a.d), ATT[a.st] + (a.st === "F" && a.j ? " (justificada)" : "")] }; }));
        }));
      cards.push(card("Faltas por dia da semana", "Clique num dia para ver a frequência só nesse dia da semana.", "w-4",
        function (w) {
          if (aRange.length < 5) return null;
          var days = [1, 2, 3, 4, 5].concat(aRange.some(function (a) { return weekday(a.d) === 6; }) ? [6] : []);
          return hbars(w, days.map(function (d) {
            var r = aRange.filter(function (a) { return weekday(a.d) === d; });
            var p = pct(r.filter(function (a) { return a.st === "F"; }).length, r.length);
            return { label: WEEKDAYS[d], value: p, valueText: p === null ? "—" : num(p, 0) + "%", cls: "is-below",
                     selected: st.weekday === d, dim: st.weekday !== null && st.weekday !== d,
                     tip: WEEKDAYS[d] + ": " + (p === null ? "sem registro" : num(p, 1) + "% de faltas em " + r.length + " registro(s)"),
                     onClick: function () { st.weekday = st.weekday === d ? null : d; update(); } };
          }), { max: 100, suffix: "%", aria: "Faltas por dia da semana" });
        }, null));
      cards.push(card("Atividades por disciplina", "Entregue no prazo, com atraso, não entregue e sem registro. Clique para filtrar pela disciplina.", "w-8",
        function (w) {
          var tRange = T.filter(function (t) { return inRange(st, t.d); });
          if (!tRange.length) return null;
          var ids = [];
          tRange.forEach(function (t) { if (ids.indexOf(t.s) === -1) ids.push(t.s); });
          ids.sort(function (a, b) { return (names[a] || "").localeCompare(names[b] || "", "pt-BR"); });
          var max = Math.max.apply(null, ids.map(function (sid) { return tRange.filter(function (t) { return t.s === sid; }).length; }));
          var wrap = h("div");
          wrap.appendChild(hbars(w, ids.map(function (sid) {
            var mine = tRange.filter(function (t) { return t.s === sid; });
            var c = function (k) { return mine.filter(function (t) { return t.st === k; }).length; };
            var on = st.subjects.indexOf(sid) !== -1;
            var del = c("E") + c("T"), reg = del + c("N");
            return { label: names[sid] || "?", stack: [{ value: c("E") }, { value: c("T"), cls: "is-alt" }, { value: c("N") + c("S"), cls: "is-below" }],
                     valueText: reg ? num(pct(del, reg), 0) + "%" : "—", selected: on, dim: st.subjects.length && !on,
                     tip: (names[sid] || "") + ": " + c("E") + " no prazo, " + c("T") + " com atraso, " + c("N") + " não entregue(s), " + c("S") + " sem registro, " + c("O") + " em aberto",
                     onClick: function () { toggle(st.subjects, sid); update(); } };
          }), { max: max, digits: 0, aria: "Atividades por disciplina" }));
          wrap.appendChild(h("div", { "class": "bx-legend" }, [h("span", { "class": "lg-1", text: "no prazo" }), h("span", { "class": "lg-2", text: "com atraso" }),
                                                               h("span", { "class": "lg-alert", text: "não entregue ou sem registro" })]));
          return wrap;
        },
        function () {
          return table([{ label: "Prazo" }, { label: "Disciplina" }, { label: "Atividade" }, { label: "Situação" }],
            tSel.map(function (t) { return { cells: [brFull(t.d), names[t.s] || "", t.t, ACT[t.st]] }; }));
        }));
      cards.push(card("Disciplina × mês", "Média das notas de cada disciplina em cada mês. Clique numa célula para filtrar o painel por aquela disciplina e mês (clique de novo para desfazer).", "",
        function () {
          var hm = monthsBetween(firstDataDay(G.map(function (g) { return g.d; }), meta.period.start, meta.period.end), meta.period.end)
            .filter(function (m) { return G.some(function (g) { return monthKey(g.d) === m; }); });
          var subs = bySubject(G).map(function (r) { return { id: r.id, name: r.name, passing: r.passing }; });
          return heatmap(subs, hm, function (sid, m) {
            var v = G.filter(function (g) { return g.s === sid && monthKey(g.d) === m; }).map(function (g) { return g.v; });
            return v.length ? { v: round(mean(v), 2), n: v.length } : null;
          }, function (sid, m) {
            var w = monthWindow(m, meta);
            return st.subjects.length === 1 && st.subjects[0] === sid && st.from === w.from && st.to === w.to;
          }, function (sid, m) { pickSubjectMonth(st, meta, sid, m); update(); });
        }, null));
      cards.push(card("Avaliações do recorte", "Ordene clicando no cabeçalho.", "",
        function () {
          if (!gBand.length) return null;
          var head = [{ label: "Data" }, { label: "Disciplina" }, { label: "Avaliação" }, { label: "Tipo" }, { label: "Nota", num: true }]
            .concat(meta.class_comparison ? [{ label: "Média da turma", num: true }] : []);
          var keyFn = [function (g) { return g.d; }, function (g) { return names[g.s] || ""; }, function (g) { return g.t; },
                       function (g) { return g.k; }, function (g) { return g.v; }, function (g) { return g.cm === null ? -1 : g.cm; }];
          var rows = gBand.slice().sort(function (a, b) {
            var x = keyFn[st.sort.key](a), y = keyFn[st.sort.key](b);
            return (x < y ? -1 : x > y ? 1 : 0) * st.sort.dir;
          });
          return table(head, rows.map(function (g) {
            var cells = [brFull(g.d), names[g.s] || "", g.t, g.k, { text: num(g.v, 1), cls: g.v < rule(g.s).passing ? "text-danger fw-semibold" : "" }];
            if (meta.class_comparison) cells.push(num(g.cm, 1));
            return { cells: cells };
          }), { sortKey: st.sort.key, sortDir: st.sort.dir,
                onSort: function (i) { st.sort = { key: i, dir: st.sort.key === i ? -st.sort.dir : (i === 0 ? -1 : 1) }; update(); } });
        }, null));
      place(f.grid, cards);
      writeHash(st);
    }
    function update() { app.render(); }
    app.render = render;
    render();
  }

  // ================================================================== turma
  function classApp(data) {
    var meta = data.meta, rules = meta.rules, names = {};
    data.subjects.forEach(function (x) { names[x.id] = x.name; });
    var S = data.students;
    var E = data.evaluations.map(function (r) { return { d: r[0], s: r[1], w: r[2], t: r[3], k: r[4] }; });
    var gradesOf = S.map(function () { return []; });
    data.grades.forEach(function (r) { gradesOf[r[0]].push({ e: r[1], v: r[2] }); });
    var attOf = S.map(function () { return []; });
    data.attendance.forEach(function (r) { attOf[r[0]].push({ d: r[1], st: r[2] }); });
    var ACTS = data.activities.map(function (r) { return { d: r[0], s: r[1], t: r[2] }; });
    var subsOf = S.map(function () { return []; });
    data.submissions.forEach(function (r) { subsOf[r[0]].push({ a: r[1], st: r[2] }); });
    var idIndex = {};
    S.forEach(function (x, i) { idIndex[x.id] = i; });
    var hs = readHash();
    var st = { from: hs.from || null, to: hs.to || null, subjects: hs.subjects || [],
               students: (hs.students || []).filter(function (id) { return id in idIndex; }),
               band: null, weekday: null, follow: !!hs.follow, sort: { key: "name", dir: 1 }, drill: null };
    function rule(sid) { return rules[String(sid)] || { formula: "aritmetica", passing: 6 }; }

    function compute(win) {
      var subjOk = function (sid) { return !st.subjects.length || st.subjects.indexOf(sid) !== -1; };
      var evalOk = E.map(function (e) { return inRange(win, e.d) && subjOk(e.s); });
      var actOk = ACTS.map(function (a) { return inRange(win, a.d) && subjOk(a.s); });
      return S.map(function (stu, i) {
        var acc = {};
        gradesOf[i].forEach(function (g) {
          if (!evalOk[g.e]) return;
          var ev = E[g.e];
          (acc[ev.s] = acc[ev.s] || []).push([g.v, ev.w]);
        });
        var subj = {};
        Object.keys(acc).forEach(function (sid) {
          var r = rule(sid), avg = average(acc[sid], r.formula);
          subj[sid] = { avg: avg, passing: r.passing };
        });
        var vals = Object.keys(subj).map(function (k) { return subj[k].avg; }).filter(function (v) { return v !== null; });
        var recs = attOf[i].filter(function (a) { return inRange(win, a.d); });
        var pres = recs.filter(function (a) { return a.st !== "F"; }).length;
        var subs = subsOf[i].filter(function (x) { return actOk[x.a]; });
        var del = subs.filter(function (x) { return x.st === "E" || x.st === "T"; }).length;
        var row = { i: i, id: stu.id, name: stu.name, url: stu.url, subj: subj,
                    overall: vals.length ? round(mean(vals), 2) : null,
                    freq: pct(pres, recs.length), absences: recs.length - pres, records: recs.length,
                    delivery: pct(del, subs.length), registered: subs.length, delivered: del, reasons: [] };
        var below = Object.keys(subj).filter(function (k) { return subj[k].avg !== null && subj[k].avg < subj[k].passing; });
        if (below.length) row.reasons.push(below.length + " disciplina(s) abaixo");
        if (row.freq !== null && row.freq < meta.min_attendance) row.reasons.push("frequência " + num(row.freq, 1) + "%");
        if (row.delivery !== null && row.registered >= 3 && row.delivery < 60) row.reasons.push("entrega " + num(row.delivery, 0) + "%");
        row.below = below.length;
        return row;
      });
    }

    /* Média da turma (média das médias), frequência e entrega de um conjunto de linhas. */
    function aggregate(list) {
      var ov = list.map(function (r) { return r.overall; }).filter(function (v) { return v !== null; });
      var recs = 0, pres = 0, reg = 0, del = 0;
      list.forEach(function (r) { recs += r.records; pres += r.records - r.absences; reg += r.registered; del += r.delivered; });
      return { n: ov.length, mean: ov.length ? round(mean(ov), 2) : null, freq: pct(pres, recs), recs: recs,
               delivery: reg ? pct(del, reg) : null, reg: reg };
    }

    function render() {
      var rows = compute(st);
      var selected = st.students.map(function (id) { return idIndex[id]; });
      var focus = selected.length ? rows.filter(function (r) { return selected.indexOf(r.i) !== -1; }) : rows;
      var shownSubjects = data.subjects.filter(function (x) { return !st.subjects.length || st.subjects.indexOf(x.id) !== -1; });
      var follow = rows.filter(function (r) { return r.reasons.length; });

      var f = frame(data, "Painel interativo — " + meta.class.name,
                    meta.class.year + " · " + meta.period.label + ". Clique num estudante, numa disciplina ou arraste na dispersão para selecionar um grupo: tudo se atualiza junto.");
      periodSlicer(f.slicers, data, st, update);
      subjectSlicer(f.slicers, data, st, update);
      var focusRow = h("div", { "class": "bx-slicer" }, [h("span", { "class": "bx-slicer-label", text: "Estudantes" }),
        chip("Todos", !selected.length && !st.follow, function () { st.students = []; st.follow = false; update(); }),
        chip("Em acompanhamento (" + follow.length + ")", st.follow, function () {
          st.follow = !st.follow;
          st.students = st.follow ? follow.map(function (r) { return r.id; }) : [];
          update();
        }, "Uma ou mais disciplinas abaixo da mínima, frequência abaixo de " + num(meta.min_attendance, 0) + "% ou entrega abaixo de 60%")]);
      f.slicers.appendChild(focusRow);
      var active = [];
      if (st.from || st.to) active.push({ label: "Datas: " + br(st.from || meta.period.start) + " a " + br(st.to || meta.period.end),
                                          remove: function () { st.from = st.to = null; update(); } });
      st.subjects.forEach(function (sid) { active.push({ label: names[sid] || "Disciplina", remove: function () { toggle(st.subjects, sid); update(); } }); });
      if (selected.length) active.push({ label: selected.length + " estudante(s) selecionado(s)",
                                         remove: function () { st.students = []; st.follow = false; update(); } });
      activeFilters(f.filters, active, function () { st.from = st.to = null; st.subjects = []; st.students = []; st.follow = false; update(); });

      if (selected.length) {
        f.selection.hidden = false;
        add(f.selection, [h("strong", { text: selected.length === 1 ? "Selecionado: " : selected.length + " selecionados: " })]);
        focus.forEach(function (r, k) {
          if (k) f.selection.appendChild(document.createTextNode(", "));
          f.selection.appendChild(r.url ? h("a", { href: r.url, text: r.name }) : h("span", { text: r.name }));
        });
        f.selection.appendChild(document.createTextNode(". Os indicadores abaixo valem para a seleção."));
        if (focus.length === 1) {  // detalhamento acessível pelo teclado (o mouse também pode clicar na nota do mapa)
          var only = focus[0];
          var detail = h("div", { "class": "bx-slicer mt-2" }, [h("span", { "class": "bx-slicer-label", text: "Detalhar" })]);
          data.subjects.forEach(function (x) {
            if (!only.subj[x.id]) return;
            var on = st.drill && st.drill.student === only.id && st.drill.subject === x.id;
            detail.appendChild(chip(x.name, on, function () {
              st.drill = on ? null : { student: only.id, subject: x.id }; update();
            }));
          });
          if (detail.children.length > 1) f.selection.appendChild(detail);
        }
      }

      var agg = aggregate(focus);
      var prev = previousWindow(st, meta), before = null;
      if (prev) {
        var prevRows = compute(prev);
        before = aggregate(selected.length ? prevRows.filter(function (r) { return selected.indexOf(r.i) !== -1; }) : prevRows);
      }
      var ov = focus.map(function (r) { return r.overall; }).filter(function (v) { return v !== null; });
      var recs = agg.recs, reg = agg.reg;
      var subjMeans = shownSubjects.map(function (x) {
        var v = focus.map(function (r) { return r.subj[x.id] ? r.subj[x.id].avg : null; }).filter(function (v) { return v !== null; });
        return { id: x.id, name: x.name, mean: v.length ? round(mean(v), 2) : null, n: v.length, passing: rule(x.id).passing,
                 below: v.filter(function (val) { return val < rule(x.id).passing; }).length };
      });
      var classMean = agg.mean, freq = agg.freq;
      add(f.kpis, [
        kpi(selected.length ? "Selecionados" : "Estudantes ativos", String(focus.length), selected.length ? "de " + S.length + " na turma" : ""),
        kpi("Média da turma", num(classMean, 1), "média das médias de " + ov.length + " estudante(s)",
            classMean !== null && classMean < 6 ? "is-alert" : "", null, before && change(classMean, before.mean, 1, "", prev)),
        kpi("Frequência", freq === null ? "—" : num(freq, 1) + "%", recs + " registro(s) de chamada",
            freq !== null && freq < meta.min_attendance ? "is-alert" : "", null, before && change(freq, before.freq, 1, " p.p.", prev)),
        kpi("Entrega de atividades", reg ? num(agg.delivery, 1) + "%" : "—", reg + " entrega(s) com registro", "", null,
            before && change(agg.delivery, before.delivery, 1, " p.p.", prev)),
        kpi("Em acompanhamento", String(focus.filter(function (r) { return r.reasons.length; }).length),
            "por nota, frequência ou entrega", follow.length ? "is-alert" : ""),
        kpi("Disciplinas com média baixa", String(subjMeans.filter(function (m) { return m.mean !== null && m.mean < m.passing; }).length),
            "de " + subjMeans.filter(function (m) { return m.mean !== null; }).length + " com notas")]);

      // ---- leitura rápida da turma (regras transparentes)
      var notes = [];
      var flagged = focus.filter(function (r) { return r.reasons.length; });
      if (flagged.length) {
        var byGrade = flagged.filter(function (r) { return r.below; }).length;
        var byAtt = flagged.filter(function (r) { return r.freq !== null && r.freq < meta.min_attendance; }).length;
        var byDel = flagged.filter(function (r) { return r.delivery !== null && r.registered >= 3 && r.delivery < 60; }).length;
        var why = [[byGrade, "por nota"], [byAtt, "por frequência"], [byDel, "por entrega"]]
          .filter(function (x) { return x[0]; }).map(function (x) { return x[0] + " " + x[1]; });
        notes.push({ tone: "alert", text: plural(flagged.length, "estudante", "estudantes") + " de " + focus.length + " em acompanhamento (" +
          listNames(why, 3) + "; um estudante pode ter mais de um motivo). ",
          action: selected.length ? null : { label: "Selecionar esses estudantes", run: function () {
            st.students = flagged.map(function (r) { return r.id; }); st.follow = true; update(); } } });
      }
      var quadrant = focus.filter(function (r) { return r.overall !== null && r.freq !== null && r.overall < 6 && r.freq < meta.min_attendance; });
      if (quadrant.length) {
        notes.push({ tone: "alert", text: plural(quadrant.length, "estudante tem", "estudantes têm") + " média e frequência abaixo das mínimas ao mesmo tempo: " +
          listNames(quadrant.map(function (r) { return r.name; })) + ". ",
          action: { label: "Selecionar", run: function () { st.students = quadrant.map(function (r) { return r.id; }); st.follow = false; update(); } } });
      }
      var withMean = subjMeans.filter(function (m) { return m.mean !== null; }).sort(function (a, c) { return a.mean - c.mean; });
      if (withMean.length > 1 && !st.subjects.length) {
        var low = withMean[0];
        notes.push({ tone: low.mean < low.passing ? "alert" : null, text: "Menor média: " + low.name + " (" + num(low.mean, 1) + "), com " +
          low.below + " de " + low.n + " abaixo da mínima. ",
          action: { label: "Filtrar " + low.name, run: function () { st.subjects = [low.id]; update(); } } });
      }
      if (prev && before && classMean !== null && before.mean !== null && Math.abs(classMean - before.mean) >= 0.3) {
        notes.push({ tone: classMean < before.mean ? "alert" : "good", text: "Em relação a " + prev.label + ", a média da turma " +
          (classMean < before.mean ? "caiu" : "subiu") + " de " + num(before.mean, 1) + " para " + num(classMean, 1) + "." });
      }
      if (prev && before && freq !== null && before.freq !== null && Math.abs(freq - before.freq) >= 3) {
        notes.push({ tone: freq < before.freq ? "alert" : "good", text: "A frequência " + (freq < before.freq ? "caiu" : "subiu") +
          " de " + num(before.freq, 1) + "% para " + num(freq, 1) + "% em relação a " + prev.label + "." });
      }
      var missing = E.map(function (e, j) { return { e: e, j: j }; }).filter(function (x) {
        return inRange(st, x.e.d) && (!st.subjects.length || st.subjects.indexOf(x.e.s) !== -1);
      }).map(function (x) {
        var got = 0;
        focus.forEach(function (r) { if (gradesOf[r.i].some(function (g) { return g.e === x.j; })) got += 1; });
        return { e: x.e, miss: focus.length - got };
      }).filter(function (x) { return x.miss >= 3; }).sort(function (a, c) { return c.miss - a.miss; });
      if (missing.length) {
        notes.push({ tone: "alert", text: plural(missing.length, "avaliação tem", "avaliações têm") + " 3 ou mais notas faltando; a maior é \u201c" +
          missing[0].e.t + "\u201d (" + br(missing[0].e.d) + "), com " + missing[0].miss + " sem nota." });
      }

      var cards = [];
      cards.push(card("Leitura rápida", "Frases geradas por regras a partir dos números deste recorte" + (selected.length ? " (só da seleção)" : "") +
                      ". Não é previsão: é um resumo para orientar a conversa.", "",
        function () { return narrative(notes); }, null, { noFocus: true }));
      if (st.drill && st.drill.student in idIndex) {
        var dr = rows[idIndex[st.drill.student]], dsub = st.drill.subject;
        cards.push(card("Detalhe: " + dr.name + " · " + (names[dsub] || ""), "Avaliações do recorte nessa disciplina, com a média da turma em cada uma.", "",
          function () {
            var evs = E.map(function (e, j) { return { e: e, j: j }; }).filter(function (x) { return x.e.s === dsub && inRange(st, x.e.d); });
            var wrap = h("div");
            var c = dr.subj[dsub], classAvgs = rows.map(function (r) { return r.subj[dsub] ? r.subj[dsub].avg : null; })
              .filter(function (v) { return v !== null; });
            wrap.appendChild(h("p", { "class": "small mb-2" }, [
              h("strong", { text: "Média do estudante: " + num(c ? c.avg : null, 1) }),
              " · média da turma na disciplina (média das médias): " + num(classAvgs.length ? mean(classAvgs) : null, 1) +
              " · mínima: " + num(rule(dsub).passing, 1) + " · fórmula: " + (rule(dsub).formula === "ponderada" ? "ponderada" :
                rule(dsub).formula === "melhor_nota" ? "melhor nota" : rule(dsub).formula === "soma" ? "soma" : "aritmética")]));
            wrap.appendChild(table([{ label: "Data" }, { label: "Avaliação" }, { label: "Tipo" }, { label: "Peso", num: true },
                                    { label: "Nota", num: true }, { label: "Turma", num: true }, { label: "Diferença", num: true }],
              evs.map(function (x) {
                var mine = gradesOf[dr.i].filter(function (g) { return g.e === x.j; })[0];
                var all = [];
                S.forEach(function (stu, i) { gradesOf[i].forEach(function (g) { if (g.e === x.j) all.push(g.v); }); });
                var cm = all.length ? mean(all) : null, diff = mine && cm !== null ? mine.v - cm : null;
                return { cells: [brFull(x.e.d), x.e.t, x.e.k, num(x.e.w, 1),
                                 { text: mine ? num(mine.v, 1) : "sem nota", cls: mine && mine.v < rule(dsub).passing ? "text-danger fw-semibold" : "" },
                                 num(cm, 1), { text: diff === null ? "—" : (diff > 0 ? "+" : diff < 0 ? "−" : "") + num(Math.abs(diff), 1),
                                               cls: diff !== null && diff <= -1 ? "text-danger fw-semibold" : "" }] };
              })));
            var actions = h("div", { "class": "d-flex flex-wrap gap-2 mt-2" }, [
              h("button", { type: "button", "class": "btn btn-sm btn-outline-secondary", text: "Fechar o detalhe",
                            on: { click: function () { st.drill = null; update(); } } }),
              dr.url ? h("a", { "class": "btn btn-sm btn-outline-primary", href: dr.url, text: "Abrir o painel de " + dr.name.split(" ")[0] }) : null]);
            wrap.appendChild(actions);
            return wrap;
          }, null, { key: "detalhe" }));
      }
      cards.push(card("Mapa da turma", "Clique no nome para selecionar o estudante; clique numa nota para ver o detalhe daquela disciplina. Ordene pelo cabeçalho. Cores: vermelho abaixo da mínima, amarelo até 1 ponto acima.", "",
        function () {
          var head = [{ label: "Estudante", key: "name" }].concat(shownSubjects.map(function (x) { return { label: x.name.length > 12 ? x.name.slice(0, 11) + "…" : x.name, key: "s" + x.id, num: true }; }))
            .concat([{ label: "Média", key: "overall", num: true }, { label: "Frequência", key: "freq", num: true }, { label: "Entrega", key: "delivery", num: true }]);
          var keyOf = function (r, k) {
            if (k === "name") return r.name;
            if (k.charAt(0) === "s") { var c = r.subj[k.slice(1)]; return c ? c.avg : null; }
            return r[k];
          };
          var list = rows.slice().sort(function (a, b) {
            var x = keyOf(a, st.sort.key), y = keyOf(b, st.sort.key);
            if (x === null && y === null) return 0;
            if (x === null) return 1;
            if (y === null) return -1;
            return (typeof x === "string" ? x.localeCompare(y, "pt-BR") : x - y) * st.sort.dir;
          });
          return table(head, list.map(function (r) {
            var isSel = selected.indexOf(r.i) !== -1;
            var nameCell = h("span", null, [h("span", { "class": "bx-name", text: r.name }),
                                            r.reasons.length ? h("span", { "class": "bx-flag", title: r.reasons.join("; "), text: "!" }) : null]);
            var cells = [{ node: nameCell }].concat(shownSubjects.map(function (x) {
              var c = r.subj[x.id];
              if (!c || c.avg === null) return { text: "—", cls: "bx-cell" };
              var heat = c.avg < c.passing ? "bx-heat-0" : c.avg < c.passing + 1 ? "bx-heat-1" : c.avg < 8.5 ? "bx-heat-2" : "bx-heat-3";
              var picked = st.drill && st.drill.student === r.id && st.drill.subject === x.id;
              return { text: num(c.avg, 1), cls: "bx-cell " + heat + (picked ? " is-picked" : ""),
                       attrs: { "data-subject": x.id, title: "Ver o detalhe de " + x.name } };
            })).concat([
              { text: num(r.overall, 1), cls: r.overall !== null && r.overall < 6 ? "text-danger fw-semibold" : "fw-semibold" },
              { text: r.freq === null ? "—" : num(r.freq, 1) + "%", cls: r.freq !== null && r.freq < meta.min_attendance ? "text-danger fw-semibold" : "" },
              { text: r.delivery === null ? "—" : num(r.delivery, 0) + "%", cls: r.delivery !== null && r.registered >= 3 && r.delivery < 60 ? "text-danger fw-semibold" : "" }]);
            return { cells: cells, selected: isSel, label: r.name, cls: isSel ? "is-selected" : (selected.length ? "is-dim" : null),
                     onClick: function (e) {
                       var cell = e && e.target && e.target.closest ? e.target.closest("td[data-subject]") : null;
                       if (cell) {  // clique numa nota: detalhe daquela disciplina para o estudante
                         var sid = +cell.getAttribute("data-subject");
                         var same = st.drill && st.drill.student === r.id && st.drill.subject === sid;
                         st.drill = same ? null : { student: r.id, subject: sid };
                         update();
                         return;
                       }
                       toggle(st.students, r.id); st.follow = false; update();
                     } };
          }), { cls: "bx-matrix", sortKey: head.map(function (c) { return c.key; }).indexOf(st.sort.key), sortDir: st.sort.dir,
                onSort: function (i) { var k = head[i].key; st.sort = { key: k, dir: st.sort.key === k ? -st.sort.dir : (k === "name" ? 1 : -1) }; update(); } });
        }, null));
      cards.push(card("Frequência × média", "Cada ponto é um estudante. Arraste para selecionar um grupo; clique num ponto para selecioná-lo.", "w-6",
        function (w) {
          var pts = rows.filter(function (r) { return r.overall !== null && r.freq !== null; });
          if (!pts.length) return null;
          return scatter(w, { passing: 6, minAtt: meta.min_attendance, aria: "Dispersão de frequência e média por estudante",
            points: pts.map(function (r) {
              var on = selected.indexOf(r.i) !== -1;
              return { id: r.id, x: r.freq, y: r.overall, selected: on, dim: selected.length && !on,
                       cls: r.overall < 6 || r.freq < meta.min_attendance ? "is-below" : "",
                       tip: r.name + ": média " + num(r.overall, 1) + ", frequência " + num(r.freq, 1) + "%",
                       onClick: function () { toggle(st.students, r.id); st.follow = false; update(); } };
            }),
            onSelect: function (ids) { st.students = ids || []; st.follow = false; update(); } });
        },
        function () {
          return table([{ label: "Estudante" }, { label: "Média", num: true }, { label: "Frequência", num: true }],
            rows.map(function (r) { return { cells: [r.name, num(r.overall, 1), r.freq === null ? "—" : num(r.freq, 1) + "%"] }; }));
        }));
      cards.push(card("Média por disciplina", "Média das médias individuais" + (selected.length ? " da seleção" : "") + ". Clique para filtrar a disciplina.", "w-6",
        function (w) {
          var all = data.subjects.map(function (x) {
            var v = focus.map(function (r) {
              var acc = [];
              gradesOf[r.i].forEach(function (g) { var ev = E[g.e]; if (ev.s === x.id && inRange(st, ev.d)) acc.push([g.v, ev.w]); });
              return average(acc, rule(x.id).formula);
            }).filter(function (v) { return v !== null; });
            return { id: x.id, name: x.name, mean: v.length ? mean(v) : null, n: v.length, passing: rule(x.id).passing,
                     below: v.filter(function (val) { return val < rule(x.id).passing; }).length };
          }).filter(function (m) { return m.mean !== null; });
          if (!all.length) return null;
          return hbars(w, all.map(function (m) {
            var on = st.subjects.indexOf(m.id) !== -1;
            return { label: m.name, value: m.mean, ref: m.passing, cls: m.mean < m.passing ? "is-below" : "", selected: on,
                     dim: st.subjects.length && !on,
                     tip: m.name + ": média " + num(m.mean, 1) + " · " + m.below + " de " + m.n + " abaixo da mínima",
                     onClick: function () { toggle(st.subjects, m.id); update(); } };
          }), { max: 10, aria: "Média por disciplina" });
        },
        function () {
          return table([{ label: "Disciplina" }, { label: "Média", num: true }, { label: "Estudantes", num: true }, { label: "Abaixo", num: true }],
            subjMeans.map(function (m) { return { cells: [m.name, num(m.mean, 1), m.n, m.below] }; }));
        }));
      var dataDates = E.map(function (e) { return e.d; }).concat(data.attendance.map(function (a) { return a[1]; }));
      var evoStart = firstDataDay(dataDates, meta.period.start, meta.period.end);
      var months = monthsBetween(evoStart, meta.period.end);
      var monthly = months.map(function (m) {
        var g = [], recsM = 0, presM = 0;
        focus.forEach(function (r) {
          gradesOf[r.i].forEach(function (x) { var ev = E[x.e]; if (monthKey(ev.d) === m && (!st.subjects.length || st.subjects.indexOf(ev.s) !== -1)) g.push(x.v); });
          attOf[r.i].forEach(function (a) { if (monthKey(a.d) === m) { recsM += 1; if (a.st !== "F") presM += 1; } });
        });
        var mid = m + "-15";
        if (mid > meta.period.end) mid = meta.period.end;
        if (mid < evoStart) mid = evoStart;
        return { m: m, d: mid, grade: g.length ? round(mean(g), 2) : null, freq: pct(presM, recsM) };
      });
      cards.push(card("Evolução mês a mês", "Linha cheia: média das notas · tracejada: frequência (eixo da direita). Arraste para escolher um intervalo.", "w-8",
        function (w) {
          if (!monthly.some(function (x) { return x.grade !== null || x.freq !== null; })) return null;
          var wrap = h("div");
          wrap.appendChild(timeline(w, { start: evoStart, end: meta.period.end, yMax: 10, y2: true, ref: 6, refLabel: "mínima",
            lines: [{ pts: monthly.map(function (x) { return [x.d, x.grade]; }) }, { pts: monthly.map(function (x) { return [x.d, x.freq]; }), cls: "is-alt", y2: true }],
            points: monthly.filter(function (x) { return x.grade !== null; }).map(function (x) {
              return { d: x.d, v: x.grade, cls: x.grade < 6 ? "is-below" : "", dim: !inRange(st, x.d), tip: monthLabel(x.m) + ": média " + num(x.grade, 1) + (x.freq !== null ? " · frequência " + num(x.freq, 1) + "%" : "") };
            }).concat(monthly.filter(function (x) { return x.freq !== null; }).map(function (x) {
              return { d: x.d, v: x.freq, y2: true, r: 4, cls: "is-alt", dim: !inRange(st, x.d), tip: monthLabel(x.m) + ": frequência " + num(x.freq, 1) + "%" };
            })),
            range: st.from || st.to ? [st.from || meta.period.start, st.to || meta.period.end] : null, aria: "Evolução mensal da média e da frequência",
            onRange: function (r) { if (r) { st.from = r[0]; st.to = r[1]; } else { st.from = st.to = null; } update(); } }));
          wrap.appendChild(h("div", { "class": "bx-legend" }, [h("span", { "class": "lg-1", text: "média das notas" }), h("span", { "class": "lg-2", text: "frequência" })]));
          return wrap;
        },
        function () {
          return table([{ label: "Mês" }, { label: "Média das notas", num: true }, { label: "Frequência", num: true }],
            monthly.map(function (x) { return { cells: [monthLabel(x.m), num(x.grade, 1), x.freq === null ? "—" : num(x.freq, 1) + "%"] }; }));
        }));
      cards.push(card("Distribuição das médias", "Clique numa faixa para selecionar esses estudantes.", "w-4",
        function (w) {
          var withAvg = rows.filter(function (r) { return r.overall !== null; });
          if (!withAvg.length) return null;
          return columns(w, BANDS.map(function (b, i) {
            var who = withAvg.filter(function (r) { return band(r.overall) === i; });
            var on = who.length && selected.length === who.length && who.every(function (r) { return selected.indexOf(r.i) !== -1; });
            return { label: b[0], value: who.length, cls: i < 3 ? "is-below" : "", selected: on,
                     tip: who.length + " estudante(s) com média entre " + b[0],
                     onClick: function () { st.students = on ? [] : who.map(function (r) { return r.id; }); st.follow = false; update(); } };
          }), { aria: "Distribuição das médias gerais" });
        }, null));
      cards.push(card("Disciplina × mês", "Média das notas" + (selected.length ? " da seleção" : " da turma") +
                      " em cada disciplina e mês. Clique numa célula para filtrar o painel por aquela disciplina e mês.", "",
        function () {
          var months = monthsBetween(firstDataDay(E.map(function (e) { return e.d; }), meta.period.start, meta.period.end), meta.period.end)
            .filter(function (m) { return E.some(function (e) { return monthKey(e.d) === m; }); });
          var subs = data.subjects.filter(function (x) { return E.some(function (e) { return e.s === x.id; }); })
            .map(function (x) { return { id: x.id, name: x.name, passing: rule(x.id).passing }; });
          return heatmap(subs, months, function (sid, m) {
            var v = [];
            focus.forEach(function (r) {
              gradesOf[r.i].forEach(function (g) { var ev = E[g.e]; if (ev.s === sid && monthKey(ev.d) === m) v.push(g.v); });
            });
            return v.length ? { v: round(mean(v), 2), n: v.length } : null;
          }, function (sid, m) {
            var w = monthWindow(m, meta);
            return st.subjects.length === 1 && st.subjects[0] === sid && st.from === w.from && st.to === w.to;
          }, function (sid, m) { pickSubjectMonth(st, meta, sid, m); update(); });
        }, null));
      cards.push(card("Avaliações do recorte", "Notas, pendências e estatística de cada avaliação" + (selected.length ? " (só da seleção)" : "") + ".", "",
        function () {
          var evs = E.map(function (e, j) { return { e: e, j: j }; }).filter(function (x) {
            return inRange(st, x.e.d) && (!st.subjects.length || st.subjects.indexOf(x.e.s) !== -1);
          });
          if (!evs.length) return null;
          return table([{ label: "Data" }, { label: "Disciplina" }, { label: "Avaliação" }, { label: "Notas", num: true },
                        { label: "Sem nota", num: true }, { label: "Média", num: true }, { label: "Mín.", num: true }, { label: "Máx.", num: true }],
            evs.slice().reverse().map(function (x) {
              var v = [];
              focus.forEach(function (r) { gradesOf[r.i].forEach(function (g) { if (g.e === x.j) v.push(g.v); }); });
              var m = v.length ? mean(v) : null;
              return { cells: [brFull(x.e.d), names[x.e.s] || "", x.e.t, v.length, focus.length - v.length,
                               { text: num(m, 1), cls: m !== null && m < rule(x.e.s).passing ? "text-danger fw-semibold" : "" },
                               num(v.length ? Math.min.apply(null, v) : null, 1), num(v.length ? Math.max.apply(null, v) : null, 1)] };
            }));
        }, null));
      place(f.grid, cards);
      writeHash(st);
    }
    function update() { app.render(); }
    app.render = render;
    render();
  }

  // ------------------------------------------------------------------ início
  root.hidden = false;
  root.appendChild(h("p", { "class": "bx-loading", text: "Carregando o painel interativo…" }));
  fetch(root.getAttribute("data-src"), { credentials: "same-origin", headers: { Accept: "application/json" } })
    .then(function (r) {
      if (!r.ok || (r.headers.get("Content-Type") || "").indexOf("json") === -1) throw new Error("http " + r.status);
      return r.json();
    })
    .then(function (data) {
      app.data = data;
      if (data.kind === "class") classApp(data); else studentApp(data);
      var timer = null;
      window.addEventListener("resize", function () { clearTimeout(timer); timer = setTimeout(function () { app.render(); }, 180); });
      document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && app.focus) { app.focus = null; app.render(); }
      });
    })
    .catch(function () {
      root.textContent = "";
      root.appendChild(h("p", { "class": "bx-loading", text: "Não foi possível carregar o painel interativo agora. O relatório detalhado abaixo continua valendo." }));
    });
})();

/* Plataforma Escolar — interações da moldura e componentes.
 *
 * Aprimoramento progressivo: sem este arquivo, todo link e formulário
 * continua funcionando. Ele acrescenta a busca global (Ctrl+K), os atalhos
 * de teclado, o menu recolhível, a ordenação de tabelas não paginadas e a
 * proteção contra envio duplo de formulário. Sem dependências.
 */
(function () {
  "use strict";

  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var urls = $("#ds-urls") ? $("#ds-urls").dataset : {};

  function store(key, value) {
    try {
      if (value === undefined) return JSON.parse(localStorage.getItem(key) || "null");
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) { return null; }  // modo privado / armazenamento bloqueado
  }

  function iconSvg(name) {
    var ns = "http://www.w3.org/2000/svg";
    var svg = document.createElementNS(ns, "svg");
    svg.setAttribute("class", "ds-icon");
    svg.setAttribute("aria-hidden", "true");
    var use = document.createElementNS(ns, "use");
    use.setAttribute("href", (urls.sprite || "") + "#i-" + name);
    svg.appendChild(use);
    return svg;
  }

  function isTyping(el) {
    if (!el) return false;
    var tag = el.tagName;
    return el.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
  }

  /* ---------- Menu recolhível ---------- */
  function toggleRail() {
    var root = document.documentElement;
    var rail = root.getAttribute("data-sidebar") !== "rail";
    if (rail) root.setAttribute("data-sidebar", "rail"); else root.removeAttribute("data-sidebar");
    document.cookie = "sidebar=" + (rail ? "rail" : "full") + "; path=/; max-age=31536000; SameSite=Lax";
    $$("[data-rail-toggle]").forEach(function (b) { b.setAttribute("aria-pressed", rail ? "true" : "false"); });
  }
  $$("[data-rail-toggle]").forEach(function (b) { b.addEventListener("click", toggleRail); });

  /* ---------- Diálogo de atalhos ---------- */
  var shortcuts = $("#shortcuts");
  function openShortcuts() { if (shortcuts && !shortcuts.open) shortcuts.showModal(); }
  $$("[data-shortcuts-open]").forEach(function (b) { b.addEventListener("click", openShortcuts); });

  /* ---------- Busca global (combobox + listbox) ---------- */
  var dialog = $("#cmdk");
  var input = $("#cmdk-input");
  var list = $("#cmdk-list");
  var dataEl = $("#cmdk-data");
  var pages = dataEl ? JSON.parse(dataEl.textContent) : [];
  var remote = [];
  var options = [];
  var activeIndex = -1;
  var timer = null;
  var lastQuery = "";
  // Por conta: num computador compartilhado da escola, recentes e favoritos
  // de uma pessoa não aparecem para a próxima que entrar.
  var USER_SUFFIX = urls.user ? ":" + urls.user : "";
  var RECENT_KEY = "ds-recent-pages" + USER_SUFFIX;

  function normalize(text) {
    return (text || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function matches(item, terms) {
    var hay = normalize(item.label + " " + (item.hint || "") + " " + (item.group || ""));
    return terms.every(function (t) { return hay.indexOf(t) !== -1; });
  }

  function highlight(label, terms) {
    // Marca o trecho encontrado sem usar innerHTML com texto do usuário.
    var frag = document.createDocumentFragment();
    var norm = normalize(label);
    var t = terms.length ? terms[0] : "";
    var i = t ? norm.indexOf(t) : -1;
    if (i < 0) { frag.appendChild(document.createTextNode(label)); return frag; }
    frag.appendChild(document.createTextNode(label.slice(0, i)));
    var mark = document.createElement("mark");
    mark.textContent = label.slice(i, i + t.length);
    frag.appendChild(mark);
    frag.appendChild(document.createTextNode(label.slice(i + t.length)));
    return frag;
  }

  function render() {
    var q = input.value.trim();
    var terms = normalize(q).split(/\s+/).filter(Boolean);
    var groups = [];
    if (!terms.length) {
      var recentKeys = store(RECENT_KEY) || [];
      var recent = recentKeys.map(function (k) {
        return pages.filter(function (p) { return p.key === k; })[0];
      }).filter(Boolean);
      var favPages = (store("ds-favorites" + USER_SUFFIX) || []).map(function (k) {
        return pages.filter(function (p) { return p.key === k; })[0];
      }).filter(Boolean);
      if (favPages.length) groups.push(["Favoritos", favPages]);
      if (recent.length) groups.push(["Recentes", recent.slice(0, 5)]);
      groups.push(["Ações", pages.filter(function (p) { return p.group === "Ações"; })]);
      groups.push(["Ir para", pages.filter(function (p) { return p.group === "Ir para"; })]);
    } else {
      var found = pages.filter(function (p) { return matches(p, terms); });
      groups.push(["Ir para", found.filter(function (p) { return p.group === "Ir para"; })]);
      groups.push(["Ações", found.filter(function (p) { return p.group === "Ações"; })]);
      ["Estudantes", "Turmas"].forEach(function (g) {
        groups.push([g, remote.filter(function (r) { return r.group === g; })]);
      });
    }

    list.textContent = "";
    options = [];
    groups.forEach(function (pair) {
      var items = pair[1];
      if (!items.length) return;
      var head = document.createElement("li");
      head.className = "cmdk-group";
      head.setAttribute("role", "presentation");
      head.textContent = pair[0];
      list.appendChild(head);
      items.forEach(function (item) {
        var li = document.createElement("li");
        li.className = "cmdk-option";
        li.id = "cmdk-opt-" + options.length;
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", "false");
        li.appendChild(iconSvg(item.icon || "arrow-right"));
        var span = document.createElement("span");
        span.appendChild(highlight(item.label, terms));
        li.appendChild(span);
        if (item.hint) {
          var small = document.createElement("small");
          small.textContent = item.hint;
          li.appendChild(small);
        }
        li.addEventListener("mousemove", function () { setActive(options.indexOf(li)); });
        li.addEventListener("click", function () { choose(item); });
        li._item = item;
        list.appendChild(li);
        options.push(li);
      });
    });
    if (!options.length) {
      var empty = document.createElement("li");
      empty.className = "cmdk-empty";
      empty.setAttribute("role", "presentation");
      empty.textContent = q.length < 2 && terms.length
        ? "Continue digitando…"
        : "Nada encontrado para “" + q + "”.";
      list.appendChild(empty);
    }
    setActive(options.length ? 0 : -1);
  }

  function setActive(i) {
    if (activeIndex >= 0 && options[activeIndex]) options[activeIndex].setAttribute("aria-selected", "false");
    activeIndex = i;
    if (i >= 0 && options[i]) {
      options[i].setAttribute("aria-selected", "true");
      input.setAttribute("aria-activedescendant", options[i].id);
      options[i].scrollIntoView({ block: "nearest" });
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  function choose(item) {
    if (item.key) {
      var recent = (store(RECENT_KEY) || []).filter(function (k) { return k !== item.key; });
      recent.unshift(item.key);
      store(RECENT_KEY, recent.slice(0, 8));
    }
    window.location.href = item.url;
  }

  function searchRemote() {
    var q = input.value.trim();
    if (q.length < 2 || !urls.search) { remote = []; render(); return; }
    if (q === lastQuery) return;
    lastQuery = q;
    fetch(urls.search + "?q=" + encodeURIComponent(q), { credentials: "same-origin", headers: { "Accept": "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { results: [] }; })
      .then(function (data) {
        if (input.value.trim() !== q) return;  // resposta antiga
        remote = data.results || [];
        render();
      })
      .catch(function () { remote = []; });
  }

  function openPalette() {
    if (!dialog || dialog.open) return;
    input.value = "";
    remote = [];
    lastQuery = "";
    render();
    dialog.showModal();
    input.focus();
  }

  if (dialog) {
    $$("[data-cmdk-open]").forEach(function (b) { b.addEventListener("click", openPalette); });
    input.addEventListener("input", function () {
      render();
      clearTimeout(timer);
      timer = setTimeout(searchRemote, 220);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); setActive(Math.min(activeIndex + 1, options.length - 1)); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(Math.max(activeIndex - 1, 0)); }
      else if (e.key === "Home" && options.length) { e.preventDefault(); setActive(0); }
      else if (e.key === "End" && options.length) { e.preventDefault(); setActive(options.length - 1); }
      else if (e.key === "Enter" && activeIndex >= 0) { e.preventDefault(); choose(options[activeIndex]._item); }
    });
    // Clique no fundo escurecido fecha.
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  }

  /* Recentes: registra o item do menu da página atual (nunca um registro). */
  var activeLink = $(".nav-item.is-active");
  if (activeLink && pages.length) {
    var current = pages.filter(function (p) { return p.url === activeLink.getAttribute("href"); })[0];
    if (current && current.key !== "home") {
      var rec = (store(RECENT_KEY) || []).filter(function (k) { return k !== current.key; });
      rec.unshift(current.key);
      store(RECENT_KEY, rec.slice(0, 8));
    }
  }

  /* ---------- Atalhos globais ---------- */
  var pendingG = false;
  var gTimer = null;
  document.addEventListener("keydown", function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      openPalette();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || isTyping(e.target)) return;
    if (dialog && dialog.open) return;
    if (e.key === "/") { e.preventDefault(); openPalette(); return; }
    if (e.key === "?") { e.preventDefault(); openShortcuts(); return; }
    if (e.key === "[" && $("[data-rail-toggle]") && window.matchMedia("(min-width: 992px)").matches) { toggleRail(); return; }
    if (pendingG) {
      pendingG = false;
      var dest = { i: urls.home, c: urls.calendar, n: urls.notifications }[e.key.toLowerCase()];
      if (dest) { e.preventDefault(); window.location.href = dest; }
      return;
    }
    if (e.key === "g" || e.key === "G") {
      pendingG = true;
      clearTimeout(gTimer);
      gTimer = setTimeout(function () { pendingG = false; }, 1200);
    }
  });

  /* ---------- Tabelas ordenáveis (data-sortable) ----------
   * Só em tabelas não paginadas: ordenar uma página de uma lista paginada
   * daria a falsa impressão de ordenar a lista inteira. */
  function cellValue(row, idx) {
    var cell = row.children[idx];
    if (!cell) return "";
    var raw = (cell.getAttribute("data-value") || cell.textContent).trim();
    var date = raw.match(/^(\d{2})\/(\d{2})\/(\d{4})/);
    if (date) return Number(date[3] + date[2] + date[1]);
    var num = raw.replace(/[%\s]/g, "").replace(/\./g, "").replace(",", ".");
    if (num !== "" && !isNaN(Number(num))) return Number(num);
    return normalize(raw);
  }
  $$("table[data-sortable]").forEach(function (table) {
    var heads = $$("thead th", table);
    heads.forEach(function (th, idx) {
      if (th.hasAttribute("data-nosort") || !th.textContent.trim()) return;
      th.setAttribute("data-sort", "");
      var btn = document.createElement("button");
      btn.type = "button";
      while (th.firstChild) btn.appendChild(th.firstChild);
      var ind = document.createElement("span");
      ind.className = "sort-ind";
      ind.setAttribute("aria-hidden", "true");
      btn.appendChild(ind);
      th.appendChild(btn);
      btn.addEventListener("click", function () {
        var asc = th.getAttribute("aria-sort") !== "ascending";
        heads.forEach(function (h) { h.removeAttribute("aria-sort"); });
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var body = table.tBodies[0];
        var rows = Array.prototype.slice.call(body.rows);
        rows.sort(function (a, b) {
          var va = cellValue(a, idx), vb = cellValue(b, idx);
          if (va < vb) return asc ? -1 : 1;
          if (va > vb) return asc ? 1 : -1;
          return 0;
        });
        rows.forEach(function (r) { body.appendChild(r); });
      });
    });
  });

  /* ---------- Prévia ao vivo (data-preview="id_do_campo") ----------
   * Mostra, ao lado do formulário, o cartão como a família vai ver. Só usa
   * textContent: o que o professor digita nunca vira HTML. */
  $$("[data-preview]").forEach(function (target) {
    var field = document.getElementById(target.getAttribute("data-preview"));
    if (!field) return;
    var placeholder = target.getAttribute("data-preview-placeholder") || "";
    var format = target.getAttribute("data-preview-format");
    function value() {
      if (field.tagName === "SELECT") {
        var opt = field.options[field.selectedIndex];
        return opt && opt.value ? opt.text : "";
      }
      var v = field.value.trim();
      if (format === "date" && /^\d{4}-\d{2}-\d{2}$/.test(v)) {
        var p = v.split("-");
        return p[2] + "/" + p[1] + "/" + p[0];
      }
      return v;
    }
    function update() {
      var v = value();
      target.textContent = v || placeholder;
      if (v) target.removeAttribute("data-preview-empty"); else target.setAttribute("data-preview-empty", "");
    }
    field.addEventListener("input", update);
    field.addEventListener("change", update);
    update();
  });

  /* ---------- Painéis de BI ---------- */
  // Seletor que navega (trocar de estudante, turma ou disciplina).
  $$("select[data-autonav]").forEach(function (sel) {
    sel.addEventListener("change", function () { if (sel.value) window.location.href = sel.value; });
  });
  // Imprimir / salvar em PDF pelo navegador.
  $$("[data-print]").forEach(function (b) { b.addEventListener("click", function () { window.print(); }); });
  // Mexer numa data torna o período "personalizado".
  $$("[data-period-date]").forEach(function (input) {
    input.addEventListener("change", function () {
      var preset = input.form && input.form.querySelector("[data-period-preset]");
      if (preset) preset.value = "personalizado";
    });
  });

  /* ---------- Filtros que se aplicam sozinhos (data-autosubmit) ----------
   * Substitui o antigo onchange="this.form.submit()", que a política de
   * segurança não permite mais. Sem JavaScript, o botão "Filtrar" do
   * formulário (escondido por .js-hide) continua funcionando. */
  document.documentElement.classList.add("js");
  $$("[data-autosubmit]").forEach(function (field) {
    field.addEventListener("change", function () {
      if (field.form) field.form.requestSubmit ? field.form.requestSubmit() : field.form.submit();
    });
  });

  // Filtro sem campos vazios no endereço: "?status=publicada" em vez de
  // "?escopo=&turma=&status=publicada". O campo desabilitado não é enviado.
  $$("form.filter-bar").forEach(function (form) {
    form.addEventListener("submit", function () {
      $$("select, input", form).forEach(function (f) { if (f.name && !f.value) f.disabled = true; });
    });
  });
  window.addEventListener("pageshow", function () {
    $$("form.filter-bar [disabled]").forEach(function (f) { f.disabled = false; });
  });

  // Campo somente leitura que seleciona o próprio texto (senha temporária).
  $$("[data-select-on-focus]").forEach(function (field) {
    field.addEventListener("focus", function () { field.select(); });
    field.addEventListener("click", function () { field.select(); });
  });

  /* ---------- Confirmação (data-confirm="mensagem") ----------
   * Em <form> ou no botão que envia. Abre um diálogo da plataforma no lugar
   * do confirm() do navegador: foco preso, Esc cancela, o botão de
   * confirmar diz o que vai acontecer (data-confirm-ok) e fica vermelho em
   * ações destrutivas (data-confirm-tone="danger"). */
  var confirmDialog = null;
  function buildConfirm() {
    var d = document.createElement("dialog");
    d.className = "ds-confirm";
    d.setAttribute("aria-labelledby", "ds-confirm-title");
    d.setAttribute("aria-describedby", "ds-confirm-msg");
    d.innerHTML =
      '<form method="dialog" class="ds-confirm-body">' +
      '<h2 id="ds-confirm-title" class="ds-confirm-title"></h2>' +
      '<p id="ds-confirm-msg" class="ds-confirm-msg"></p>' +
      '<div class="ds-confirm-actions">' +
      '<button value="cancel" class="btn btn-outline-secondary" type="submit">Cancelar</button>' +
      '<button value="ok" class="btn btn-primary" type="submit" data-confirm-ok></button>' +
      "</div></form>";
    d.addEventListener("click", function (e) { if (e.target === d) d.close("cancel"); });
    document.body.appendChild(d);
    return d;
  }
  function askConfirm(source, onOk) {
    confirmDialog = confirmDialog || buildConfirm();
    var tone = source.getAttribute("data-confirm-tone");
    var ok = $("[data-confirm-ok]", confirmDialog);
    $("#ds-confirm-title", confirmDialog).textContent = source.getAttribute("data-confirm-title") || "Confirmar ação";
    $("#ds-confirm-msg", confirmDialog).textContent = source.getAttribute("data-confirm");
    ok.textContent = source.getAttribute("data-confirm-ok") || "Confirmar";
    ok.className = "btn " + (tone === "danger" ? "btn-danger" : "btn-primary");
    confirmDialog.returnValue = "";
    confirmDialog.onclose = function () { if (confirmDialog.returnValue === "ok") onOk(); };
    confirmDialog.showModal();
    // Foco no "Cancelar": Enter por engano nunca apaga nada.
    $("button[value=cancel]", confirmDialog).focus();
  }
  document.addEventListener("submit", function (e) {
    var form = e.target;
    var btn = e.submitter;
    var source = btn && btn.hasAttribute("data-confirm") ? btn : (form.hasAttribute("data-confirm") ? form : null);
    if (!source || form._confirmed) { form._confirmed = false; return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    askConfirm(source, function () {
      form._confirmed = true;
      if (form.requestSubmit) form.requestSubmit(btn || undefined); else form.submit();
    });
  }, true);

  /* ---------- Tabela que vira lista no celular (.table-stack) ----------
   * Copia o título de cada coluna para as células que ainda não têm
   * data-label; o CSS o mostra antes do valor em telas estreitas. */
  $$("table.table-stack").forEach(function (table) {
    // Só o texto visível do título: "(ordem decrescente)" e "Ações" ocultos
    // são para o leitor de tela, não para virar rótulo de cada linha.
    var labels = $$("thead th", table).map(function (th) {
      var copy = th.cloneNode(true);
      $$(".visually-hidden", copy).forEach(function (el) { el.remove(); });
      return copy.textContent.trim();
    });
    $$("tbody tr", table).forEach(function (tr) {
      Array.prototype.forEach.call(tr.children, function (cell, i) {
        if (!cell.hasAttribute("data-label") && labels[i] && !cell.hasAttribute("colspan")) cell.setAttribute("data-label", labels[i]);
      });
    });
  });

  /* ---------- Seleção em lote (data-bulk) ----------
   * Um formulário com caixas name="ids", uma caixa "todas" (data-bulk-all)
   * e uma barra (data-bulk-bar) que mostra quantos estão marcados e só
   * habilita as ações com pelo menos um. */
  $$("[data-bulk]").forEach(function (form) {
    var boxes = $$("input[type=checkbox][name=ids]", form);
    var all = $("[data-bulk-all]", form);
    var bar = $("[data-bulk-bar]", form);
    var count = $("[data-bulk-count]", form);
    function sync() {
      var n = boxes.filter(function (b) { return b.checked; }).length;
      if (count) count.textContent = n === 1 ? "1 selecionado" : n + " selecionados";
      if (bar) {
        bar.classList.toggle("is-active", n > 0);
        $$("button", bar).forEach(function (b) { b.disabled = n === 0; });
      }
      if (all) {
        all.checked = n > 0 && n === boxes.length;
        all.indeterminate = n > 0 && n < boxes.length;
      }
      boxes.forEach(function (b) { var tr = b.closest("tr"); if (tr) tr.classList.toggle("is-selected", b.checked); });
    }
    boxes.forEach(function (b) { b.addEventListener("change", sync); });
    if (all) all.addEventListener("change", function () { boxes.forEach(function (b) { b.checked = all.checked; }); sync(); });
    sync();
  });

  /* ---------- Preencher vários campos de uma vez (data-fill-all) ----------
   * data-fill-all="seletor" data-fill-value="valor": usado em "marcar todos
   * como entregues" e "limpar". */
  $$("[data-fill-all]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var value = btn.getAttribute("data-fill-value") || "";
      $$(btn.getAttribute("data-fill-all")).forEach(function (field) {
        field.value = value;
        field.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
  });

  /* ---------- Enter vai para o próximo campo (data-enter-next) ----------
   * No lançamento de notas, Enter num campo leva ao do próximo estudante em
   * vez de enviar o formulário pela metade. No último campo, envia. */
  $$("[data-enter-next]").forEach(function (scope) {
    scope.addEventListener("keydown", function (e) {
      if (e.key !== "Enter" || e.target.tagName !== "INPUT") return;
      var fields = $$("input:not([type=hidden]):not([disabled])", scope);
      var i = fields.indexOf(e.target);
      if (i < 0 || i === fields.length - 1) return;
      e.preventDefault();
      fields[i + 1].focus();
      fields[i + 1].select();
    });
  });

  /* ---------- Favoritos ----------
   * A estrela da barra superior guarda a página atual do menu neste
   * navegador (não vai para o servidor) e a mostra no topo do menu. */
  var FAV_KEY = "ds-favorites" + USER_SUFFIX;
  var favToggle = $("[data-fav-toggle]");
  var favList = $("[data-fav-list]");
  var currentPage = activeLink && pages.filter(function (p) { return p.url === activeLink.getAttribute("href"); })[0];
  function renderFavorites() {
    var favs = (store(FAV_KEY) || []).map(function (k) {
      return pages.filter(function (p) { return p.key === k; })[0];
    }).filter(Boolean);
    if (favList) {
      favList.textContent = "";
      favList.closest("[data-fav-section]").hidden = !favs.length;
      favs.forEach(function (p) {
        var a = document.createElement("a");
        a.className = "nav-item";
        a.href = p.url;
        a.title = p.label;
        a.appendChild(iconSvg(p.icon || "star"));
        var span = document.createElement("span");
        span.className = "nav-label";
        span.textContent = p.label;
        a.appendChild(span);
        var li = document.createElement("li");
        li.appendChild(a);
        favList.appendChild(li);
      });
    }
    if (favToggle) {
      var on = currentPage && favs.some(function (p) { return p.key === currentPage.key; });
      favToggle.setAttribute("aria-pressed", on ? "true" : "false");
      favToggle.setAttribute("aria-label", on ? "Tirar dos favoritos" : "Adicionar aos favoritos");
      favToggle.title = favToggle.getAttribute("aria-label");
    }
  }
  if (favToggle) {
    // Só páginas do menu podem virar favorito (nunca a ficha de um estudante).
    favToggle.hidden = !currentPage || currentPage.key === "home";
    favToggle.addEventListener("click", function () {
      var favs = (store(FAV_KEY) || []).filter(function (k) { return k !== currentPage.key; });
      if (favToggle.getAttribute("aria-pressed") !== "true") favs.unshift(currentPage.key);
      store(FAV_KEY, favs.slice(0, 8));
      renderFavorites();
    });
  }
  renderFavorites();

  /* ---------- Envio único de formulário ----------
   * Desabilita o botão DEPOIS que o envio começou (setTimeout): desabilitar
   * no próprio evento tiraria o nome do botão dos dados enviados, e o
   * "Publicar" chegaria ao servidor como "Salvar rascunho". */
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form.method.toLowerCase() !== "post" || e.defaultPrevented) return;
    var btn = e.submitter;
    setTimeout(function () {
      form.setAttribute("aria-busy", "true");
      if (btn) { btn.disabled = true; btn.classList.add("is-loading"); }
    }, 0);
  });
  // Ao voltar pelo histórico, a página pode vir do cache com o botão travado.
  window.addEventListener("pageshow", function () {
    $$("form[aria-busy]").forEach(function (f) { f.removeAttribute("aria-busy"); });
    $$("button.is-loading").forEach(function (b) { b.disabled = false; b.classList.remove("is-loading"); });
  });
})();

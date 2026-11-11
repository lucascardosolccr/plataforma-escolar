"""Gráficos SVG gerados no servidor — sem JavaScript e sem dependências externas.

Cada função devolve HTML (``SafeString``) com um ``<svg>`` acessível: os rótulos
são escapados e cada ponto traz um ``<title>`` com o valor, permitindo ao
usuário ver o dado que fundamenta o gráfico (requisito de rastreabilidade).
"""

from django.utils.html import escape
from django.utils.safestring import mark_safe


def _empty(message="Sem dados para exibir."):
    return mark_safe(
        f'<div class="chart-empty text-body-secondary small py-4 text-center">{escape(message)}</div>'
    )


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, float):
        # Vírgula decimal, como nas tabelas da mesma tela ("93,9%", não "93.9").
        return f"{value:g}".replace(".", ",")
    return str(value)


def _summary(kind, items, suffix):
    """Nome acessível do gráfico: o tipo e os valores, na ordem exibida.

    O leitor de tela anuncia o que a imagem mostra em vez de "imagem".
    """
    partes = [
        f"{i['label']}: {_fmt(i.get('value'))}{suffix if i.get('value') is not None else ''}"
        for i in items
    ]
    return escape(f"{kind}. " + "; ".join(partes))


def _grid_lines(pad_l, pad_t, plot_w, plot_h, steps=4):
    """Linhas de grade horizontais discretas (25%, 50%, 75%)."""
    out = []
    for k in range(1, steps):
        y = pad_t + plot_h * k / steps
        out.append(
            f'<line x1="{pad_l}" y1="{y:.1f}" x2="{pad_l + plot_w}" y2="{y:.1f}" class="chart-grid"/>'
        )
    return "".join(out)


def line_chart(points, *, y_min=0.0, y_max=None, suffix="", width=520, height=220):
    """points: lista de {"label": str, "value": number}.

    Gráfico de linhas para evolução (notas, frequência…)."""
    values = [p["value"] for p in points if p.get("value") is not None]
    if not values:
        return _empty()
    if y_max is None:
        y_max = max(values) if max(values) > 0 else 1
    if y_max == y_min:
        y_max = y_min + 1

    pad_l, pad_r, pad_t, pad_b = 40, 16, 16, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(points)

    def x(i):
        return pad_l + (plot_w * i / (n - 1) if n > 1 else plot_w / 2)

    def y(v):
        return pad_t + plot_h - (plot_h * (v - y_min) / (y_max - y_min))

    coords = []
    circles = []
    for i, p in enumerate(points):
        v = p.get("value")
        if v is None:
            continue
        cx, cy = x(i), y(v)
        coords.append(f"{cx:.1f},{cy:.1f}")
        circles.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" class="chart-dot">'
            f"<title>{escape(str(p['label']))}: {_fmt(v)}{escape(suffix)}</title></circle>"
        )
    poly = (
        f'<polyline points="{" ".join(coords)}" class="chart-line" fill="none"/>'
        if len(coords) > 1
        else ""
    )

    grid = (
        _grid_lines(pad_l, pad_t, plot_w, plot_h) +
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="chart-axis"/>'
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="chart-axis"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + 4}" class="chart-tick" text-anchor="end">{_fmt(round(y_max, 1))}</text>'
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" class="chart-tick" text-anchor="end">{_fmt(round(y_min, 1))}</text>'
    )
    if n <= 8:
        labels = "".join(
            f'<text x="{x(i):.1f}" y="{height - 12}" class="chart-tick" text-anchor="middle">{escape(str(p["label"]))}</text>'
            for i, p in enumerate(points)
        )
    else:
        labels = (
            f'<text x="{x(0):.1f}" y="{height - 12}" class="chart-tick" text-anchor="start">{escape(str(points[0]["label"]))}</text>'
            f'<text x="{x(n - 1):.1f}" y="{height - 12}" class="chart-tick" text-anchor="end">{escape(str(points[-1]["label"]))}</text>'
        )
    area = ""
    if len(coords) > 1:
        base = pad_t + plot_h
        first_x, last_x = coords[0].split(",")[0], coords[-1].split(",")[0]
        area = (
            f'<polygon points="{first_x},{base:.1f} {" ".join(coords)} {last_x},{base:.1f}" '
            f'class="chart-area"/>'
        )
    nome = _summary("Gráfico de linha", points, suffix)
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{nome}">'
        f"{grid}{area}{poly}{''.join(circles)}{labels}</svg>"
    )


def _short(text, limit):
    text = str(text)
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _bar_tick(cx, height, item, slot):
    # Cerca de 6,5 px por caractere na fonte do eixo: o corte acompanha a
    # largura da faixa de cada barra, para rótulos vizinhos não se sobreporem.
    limit = max(4, int(slot / 6.5))
    first = escape(_short(item.get("tick") or item["label"], limit))
    if not item.get("sub"):
        return f'<text x="{cx:.1f}" y="{height - 14}" class="chart-tick" text-anchor="middle">{first}</text>'
    return (
        f'<text x="{cx:.1f}" y="{height - 22}" class="chart-tick" text-anchor="middle">{first}'
        f'<tspan x="{cx:.1f}" dy="13">{escape(_short(item["sub"], limit))}</tspan></text>'
    )


def bar_chart(items, *, max_value=None, suffix="", width=520, height=220):
    """items: lista de {"label", "value", "below" (opcional bool)} — barras verticais.

    "tick" e "sub" (opcionais) dão o rótulo curto do eixo em uma ou duas
    linhas; o rótulo completo fica no <title> e no aria-label.
    """
    values = [i["value"] for i in items if i.get("value") is not None]
    if not values:
        return _empty()
    if max_value is None:
        max_value = max(values) if max(values) > 0 else 1

    pad_l, pad_r, pad_t, pad_b = 40, 16, 18, 40
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(items)
    slot = plot_w / n
    bar_w = min(48, slot * 0.6)

    bars = []
    for i, item in enumerate(items):
        v = item.get("value")
        if v is None:
            continue
        bar_h = plot_h * (v / max_value)
        cx = pad_l + slot * i + slot / 2
        bx = cx - bar_w / 2
        by = pad_t + plot_h - bar_h
        cls = "chart-bar below" if item.get("below") else "chart-bar"
        barra = (
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" class="{cls}">'
            f"<title>{escape(str(item['label']))}: {_fmt(v)}{escape(suffix)}</title></rect>"
        )
        if item.get("url"):
            # Detalhamento: a barra leva aos registros que formam o valor.
            barra = (
                f'<a href="{escape(item["url"])}" aria-label="{escape(str(item["label"]))}: '
                f'{_fmt(v)}{escape(suffix)} — ver registros">{barra}</a>'
            )
        bars.append(
            barra
            + f'<text x="{cx:.1f}" y="{by - 5:.1f}" class="chart-value" text-anchor="middle">{_fmt(v)}</text>'
            + _bar_tick(cx, height, item, slot)
        )
    grid = (
        _grid_lines(pad_l, pad_t, plot_w, plot_h) +
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="chart-axis"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + 4}" class="chart-tick" text-anchor="end">{_fmt(round(max_value, 1))}</text>'
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" class="chart-tick" text-anchor="end">0</text>'
    )
    nome = _summary("Gráfico de barras", items, suffix)
    # Com barras clicáveis (filtro), o gráfico é um grupo de links: "imagem" esconderia os links do leitor de
    # tela e o axe aponta elemento interativo dentro de imagem.
    role = "group" if any(i.get("url") for i in items) else "img"
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="{role}" aria-label="{nome}">'
        f'{grid}{"".join(bars)}</svg>'
    )


def h_bars(items, *, max_value=None, suffix=""):
    """Barras horizontais com rótulo à esquerda (distribuições, totais)."""
    values = [i["value"] for i in items if i.get("value") is not None]
    if not values:
        return _empty()
    if max_value is None:
        max_value = max(values) if max(values) > 0 else 1
    rows = []
    for item in items:
        v = item.get("value") or 0
        pct = (v / max_value * 100) if max_value else 0
        cls = "chart-hbar-fill below" if item.get("below") else "chart-hbar-fill"
        rows.append(
            f'<div class="chart-hbar">'
            f'<div class="chart-hbar-label">{escape(str(item["label"]))}</div>'
            # SVG com largura em atributo: a CSP não aceita style="" embutido.
            f'<svg class="chart-hbar-track" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">'
            f'<rect class="chart-hbar-bg" width="100" height="10"/>'
            f'<rect class="{cls}" width="{pct:.1f}" height="10"/></svg>'
            f'<div class="chart-hbar-value">{_fmt(v)}{escape(suffix)}</div>'
            f"</div>"
        )
    return mark_safe("".join(rows))


def gauge(percent, *, limit=None, label=""):
    """Indicador de frequência (0–100%) com marca opcional de limite de faltas."""
    if percent is None:
        return _empty()
    pct = max(0.0, min(100.0, float(percent)))
    danger = limit is not None and (100 - pct) >= limit
    marker = ""
    if limit is not None:
        pos = max(0.0, min(100.0, 100 - float(limit)))
        marker = (
            f'<line class="chart-gauge-marker" x1="{pos:.1f}" x2="{pos:.1f}" y1="0" y2="10">'
            f"<title>Limite de faltas ({_fmt(limit)}%)</title></line>"
        )
    return mark_safe(
        f'<div class="chart-gauge-wrap">'
        f'<svg class="chart-gauge" viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true">'
        f'<rect class="chart-gauge-bg" width="100" height="10"/>'
        f'<rect class="chart-gauge-fill{" danger" if danger else ""}" width="{pct:.1f}" height="10"/>'
        f"{marker}</svg>"
        f'<div class="chart-gauge-value">{_fmt(pct)}% {escape(label)}</div>'
        f"</div>"
    )


def trend_chart(points, *, line=None, projection=None, reference=None, mark=None, suffix="", scale=10,
                width=560, height=220):
    """Série no tempo com a tendência robusta (cognitio.trajectory).

    points: [(data, valor de 0 a 1)]; line: (data inicial, intercepto, inclinação por dia);
    projection: {"date", "value", "low", "high"}; reference: valor de 0 a 1 (média de aprovação);
    mark: data em que a queda em curso começou. Os valores aparecem multiplicados por ``scale``."""
    if not points:
        return _empty()
    pad_l, pad_r, pad_t, pad_b = 40, 16, 16, 34
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    d0 = points[0][0]
    d1 = max([points[-1][0]] + ([projection["date"]] if projection else []))
    span = max((d1 - d0).days, 1)

    def x(d):
        return pad_l + plot_w * (d - d0).days / span

    def y(v):
        return pad_t + plot_h - plot_h * min(max(v, 0.0), 1.0)

    def val(v):
        return _fmt(round(v * scale, 1))

    out = [_grid_lines(pad_l, pad_t, plot_w, plot_h),
           f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="chart-axis"/>',
           f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="chart-axis"/>',
           f'<text x="{pad_l - 6}" y="{pad_t + 4}" class="chart-tick" text-anchor="end">{_fmt(scale)}</text>',
           f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" class="chart-tick" text-anchor="end">0</text>']
    if reference is not None:
        out.append(f'<line x1="{pad_l}" y1="{y(reference):.1f}" x2="{pad_l + plot_w}" y2="{y(reference):.1f}" '
                   f'class="chart-ref"><title>Média de aprovação: {val(reference)}{escape(suffix)}</title></line>')
    if projection and line:
        last = points[-1][0]
        ly = line[1] + line[2] * (last - line[0]).days
        out.append(f'<polygon points="{x(last):.1f},{y(ly):.1f} {x(projection["date"]):.1f},{y(projection["high"]):.1f} '
                   f'{x(projection["date"]):.1f},{y(projection["low"]):.1f}" class="chart-band">'
                   f'<title>Faixa se a tendência continuar: {val(projection["low"])} a {val(projection["high"])}'
                   f'{escape(suffix)}</title></polygon>')
        out.append(f'<line x1="{x(last):.1f}" y1="{y(ly):.1f}" x2="{x(projection["date"]):.1f}" '
                   f'y2="{y(projection["value"]):.1f}" class="chart-proj"/>')
    if line:
        first, last = points[0][0], points[-1][0]
        out.append(f'<line x1="{x(first):.1f}" y1="{y(line[1] + line[2] * (first - line[0]).days):.1f}" '
                   f'x2="{x(last):.1f}" y2="{y(line[1] + line[2] * (last - line[0]).days):.1f}" class="chart-trend">'
                   f'<title>Tendência (Theil–Sen)</title></line>')
    if mark:
        out.append(f'<line x1="{x(mark):.1f}" y1="{pad_t}" x2="{x(mark):.1f}" y2="{pad_t + plot_h}" class="chart-mark">'
                   f'<title>Queda em curso desde {mark:%d/%m/%Y}</title></line>')
    for d, v in points:
        out.append(f'<circle cx="{x(d):.1f}" cy="{y(v):.1f}" r="3" class="chart-dot">'
                   f'<title>{d:%d/%m/%Y}: {val(v)}{escape(suffix)}</title></circle>')
    out.append(f'<text x="{pad_l}" y="{height - 12}" class="chart-tick" text-anchor="start">{d0:%d/%m}</text>'
               f'<text x="{pad_l + plot_w}" y="{height - 12}" class="chart-tick" text-anchor="end">{d1:%d/%m}</text>')
    nome = escape(f"Evolução de {len(points)} resultados entre {d0:%d/%m/%Y} e {points[-1][0]:%d/%m/%Y}"
                  + (f"; queda em curso desde {mark:%d/%m/%Y}" if mark else ""))
    return mark_safe(f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{nome}">'
                     + "".join(out) + "</svg>")


def control_chart(chart, *, width=640, height=240):
    """Carta de controle (``core.stats.laney_p``): proporção semanal, linha central e limites por semana.

    Pontos fora dos limites ficam destacados; cada ponto traz a semana, o percentual e os limites no ``<title>``."""
    pts = chart["points"] if chart else []
    if len(pts) < 2:
        return _empty("Poucas semanas com chamada para desenhar a carta.")
    lo_all = min(min(p["low"], p["p"]) for p in pts)
    hi_all = max(max(p["high"], p["p"]) for p in pts)
    y_min, y_max = max(0.0, lo_all - 0.02), min(1.0, hi_all + 0.02)
    if y_max - y_min < 0.05:
        y_max = min(1.0, y_min + 0.05)
    pad_l, pad_r, pad_t, pad_b = 44, 16, 16, 34
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b
    n = len(pts)

    def x(i):
        return pad_l + plot_w * i / (n - 1)

    def y(v):
        return pad_t + plot_h - plot_h * (v - y_min) / (y_max - y_min)

    def pc(v):
        return _fmt(round(100 * v, 1)) + "%"

    out = [_grid_lines(pad_l, pad_t, plot_w, plot_h),
           f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="chart-axis"/>',
           f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="chart-axis"/>',
           f'<text x="{pad_l - 6}" y="{pad_t + 4}" class="chart-tick" text-anchor="end">{pc(y_max)}</text>',
           f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" class="chart-tick" text-anchor="end">{pc(y_min)}</text>']
    for key in ("low", "high"):
        coords = " ".join(f"{x(i):.1f},{y(p[key]):.1f}" for i, p in enumerate(pts))
        out.append(f'<polyline points="{coords}" class="chart-limit" fill="none">'
                   f'<title>Limite {"inferior" if key == "low" else "superior"} de controle</title></polyline>')
    cy = y(chart["center"])
    out.append(f'<line x1="{pad_l}" y1="{cy:.1f}" x2="{pad_l + plot_w}" y2="{cy:.1f}" class="chart-ref">'
               f'<title>Média: {pc(chart["center"])}</title></line>')
    out.append('<polyline points="' + " ".join(f"{x(i):.1f},{y(p['p']):.1f}" for i, p in enumerate(pts))
               + '" class="chart-line" fill="none"/>')
    for i, p in enumerate(pts):
        cls = "chart-dot is-signal" if p["signal"] else "chart-dot"
        label = p["label"].strftime("%d/%m/%Y") if hasattr(p["label"], "strftime") else str(p["label"])
        out.append(f'<circle cx="{x(i):.1f}" cy="{y(p["p"]):.1f}" r="{4 if p["signal"] else 3}" class="{cls}">'
                   f'<title>Semana de {escape(label)}: {pc(p["p"])} (limites {pc(p["low"])} a {pc(p["high"])}; '
                   f'{p["n"]} registros){" — fora dos limites" if p["signal"] else ""}</title></circle>')
    first, last = pts[0]["label"], pts[-1]["label"]
    fmt = (lambda d: d.strftime("%d/%m")) if hasattr(first, "strftime") else str
    out.append(f'<text x="{pad_l}" y="{height - 12}" class="chart-tick" text-anchor="start">{escape(fmt(first))}</text>'
               f'<text x="{pad_l + plot_w}" y="{height - 12}" class="chart-tick" text-anchor="end">{escape(fmt(last))}</text>')
    fora = sum(1 for p in pts if p["signal"])
    nome = escape(f"Carta de controle da frequência em {n} semanas; média {pc(chart['center'])}; "
                  f"{fora} semana(s) fora dos limites")
    return mark_safe(f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{nome}">'
                     + "".join(out) + "</svg>")

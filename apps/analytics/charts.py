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
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{nome}">'
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
            f'<div class="chart-hbar-track"><div class="{cls}" style="width:{pct:.1f}%"></div></div>'
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
        marker = f'<div class="chart-gauge-marker" style="left:{pos:.1f}%" title="Limite de faltas ({_fmt(limit)}%)"></div>'
    return mark_safe(
        f'<div class="chart-gauge-wrap">'
        f'<div class="chart-gauge">'
        f'<div class="chart-gauge-fill{" danger" if danger else ""}" style="width:{pct:.1f}%"></div>'
        f"{marker}</div>"
        f'<div class="chart-gauge-value">{_fmt(pct)}% {escape(label)}</div>'
        f"</div>"
    )

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
        return f"{value:g}"
    return str(value)


def line_chart(points, *, y_min=0.0, y_max=None, suffix="", width=640, height=220):
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
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img">{grid}{poly}{"".join(circles)}{labels}</svg>'
    )


def bar_chart(items, *, max_value=None, suffix="", width=640, height=220):
    """items: lista de {"label", "value", "below" (opcional bool)} — barras verticais."""
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
        bars.append(
            f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" rx="4" class="{cls}">'
            f"<title>{escape(str(item['label']))}: {_fmt(v)}{escape(suffix)}</title></rect>"
            f'<text x="{cx:.1f}" y="{by - 4:.1f}" class="chart-tick" text-anchor="middle">{_fmt(v)}</text>'
            f'<text x="{cx:.1f}" y="{height - 14}" class="chart-tick" text-anchor="middle">{escape(str(item["label"]))[:14]}</text>'
        )
    grid = (
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" y2="{pad_t + plot_h}" class="chart-axis"/>'
        f'<text x="{pad_l - 6}" y="{pad_t + 4}" class="chart-tick" text-anchor="end">{_fmt(round(max_value, 1))}</text>'
        f'<text x="{pad_l - 6}" y="{pad_t + plot_h}" class="chart-tick" text-anchor="end">0</text>'
    )
    return mark_safe(
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img">{grid}{"".join(bars)}</svg>'
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

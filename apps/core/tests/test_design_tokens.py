"""Contraste dos tokens de cor (WCAG 2.2), nos temas claro e escuro.

O design system declara as combinações de texto e fundo. Este teste lê
static/css/ds-tokens.css e calcula a razão de contraste de cada par: se
alguém trocar uma cor e deixar um texto ilegível, a suíte falha.
Texto: mínimo 4,5:1 (AA). Bordas de campo e indicadores: 3:1 (1.4.11).
"""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

TOKENS = Path(settings.BASE_DIR) / "static" / "css" / "ds-tokens.css"


def _block(css, selector):
    start = css.index(selector)
    open_ = css.index("{", start)
    depth, i = 0, open_
    while True:
        if css[i] == "{":
            depth += 1
        elif css[i] == "}":
            depth -= 1
            if depth == 0:
                return css[open_ + 1:i]
        i += 1


def _vars(block):
    return dict(re.findall(r"--(ds-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))


def _lum(hex_):
    rgb = [int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# (frente, fundo, mínimo)
TEXT_PAIRS = [
    ("ds-text", "ds-paper", 4.5),
    ("ds-text", "ds-surface", 4.5),
    ("ds-text", "ds-surface-2", 4.5),
    ("ds-text-muted", "ds-paper", 4.5),
    ("ds-text-muted", "ds-surface", 4.5),
    ("ds-text-muted", "ds-surface-2", 4.5),
    ("ds-primary", "ds-surface", 4.5),
    ("ds-primary", "ds-paper", 4.5),
    ("ds-primary", "ds-primary-soft", 4.5),
    ("ds-success", "ds-success-bg", 4.5),
    ("ds-warning", "ds-warning-bg", 4.5),
    ("ds-danger", "ds-danger-bg", 4.5),
    ("ds-info", "ds-info-bg", 4.5),
    ("ds-success", "ds-surface", 4.5),  # célula "em consolidação"
    ("ds-on-danger", "ds-danger", 4.5),  # "falta" marcada na frequência
    ("ds-on-mark", "ds-mark", 4.5),
    ("ds-frame-text", "ds-frame", 4.5),
    ("ds-frame-muted", "ds-frame", 4.5),
    ("ds-frame-muted", "ds-frame-2", 4.5),
    ("ds-line-strong", "ds-surface", 3.0),
    ("ds-focus", "ds-paper", 3.0),
    ("ds-mark", "ds-frame", 3.0),
]


class TokenContrastTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        css = TOKENS.read_text(encoding="utf-8")
        cls.light = _vars(_block(css, ":root,"))
        cls.dark = {**cls.light, **_vars(_block(css, '[data-bs-theme="dark"] {'))}

    def _check(self, theme, values):
        falhas = []
        for fg, bg, minimo in TEXT_PAIRS:
            if fg not in values or bg not in values:
                continue
            ratio = contrast(values[fg], values[bg])
            if ratio < minimo:
                falhas.append(f"{theme}: {fg} sobre {bg} = {ratio:.2f} (mín. {minimo})")
        self.assertEqual(falhas, [])

    def test_light_theme_pairs(self):
        self._check("claro", self.light)

    def test_dark_theme_pairs(self):
        self._check("escuro", self.dark)

    def test_primary_button_text_contrast(self):
        self.assertGreaterEqual(contrast("#ffffff", self.light["ds-primary"]), 4.5)
        self.assertGreaterEqual(contrast("#ffffff", self.dark["ds-btn-primary"]), 4.5)

    def test_reference_value(self):
        """Confere a fórmula com um valor conhecido (preto/branco = 21:1)."""
        self.assertAlmostEqual(contrast("#000000", "#ffffff"), 21.0, places=1)


def _resolve(value, env):
    """Cor hexadecimal de ``value`` no tema (var() com ou sem alternativa, ou literal); None se não der."""
    value = value.replace("!important", "").strip()
    for _ in range(5):
        m = re.fullmatch(r"var\(--([a-z0-9-]+)\s*(?:,\s*(.+))?\)", value)
        if not m:
            break
        value = env.get(m.group(1)) or (m.group(2) or "").strip()
    value = {"#fff": "#ffffff", "#000": "#000000", "white": "#ffffff"}.get(value, value)
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None


def _over(hex_fg, hex_bg, alpha):
    a = [int(hex_fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * alpha + y * (1 - alpha)):02x}" for x, y in zip(a, b))


class RuleContrastTests(SimpleTestCase):
    """Regras com cor de texto e de fundo próprias, nos dois temas, com ``opacity`` aplicada.

    Pega o que o teste dos tokens não vê: branco fixo sobre um token que fica claro no tema escuro (era o
    caso da "falta" marcada e do passo atual da importação) e ``opacity`` que clareia o texto (célula "em
    consolidação" e placeholder)."""

    def test_rules_with_own_text_and_background(self):
        css_dir = TOKENS.parent
        tokens = TOKENS.read_text(encoding="utf-8")
        light = _vars(_block(tokens, ":root,"))
        dark = {**light, **_vars(_block(tokens, '[data-bs-theme="dark"] {'))}
        falhas, checked = [], 0
        for name in ("ds-components.css", "ds-shell.css", "ds-features.css"):
            css = re.sub(r"/\*.*?\*/", "", (css_dir / name).read_text(encoding="utf-8"), flags=re.S)
            for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
                d = dict((k.strip(), v.strip()) for k, v in re.findall(r"([a-z-]+)\s*:\s*([^;]+)", body))
                bg_decl = d.get("background-color") or d.get("background")
                if "color" not in d or not bg_decl:
                    continue
                op = d.get("opacity", "1")
                op = float(op) if re.fullmatch(r"[\d.]+", op) else 1.0
                for theme, env in (("claro", light), ("escuro", dark)):
                    fg, bg, surface = _resolve(d["color"], env), _resolve(bg_decl, env), env["ds-surface"]
                    if not (fg and bg):
                        continue
                    checked += 1
                    if op < 1:
                        fg, bg = _over(fg, surface, op), _over(bg, surface, op)
                    ratio = contrast(fg, bg)
                    if ratio < 4.5:
                        falhas.append(f"{theme}: {sel.strip()[:60]} = {ratio:.2f}")
        self.assertGreater(checked, 20)  # a leitura das regras funcionou
        self.assertEqual(falhas, [])

    def test_placeholder_keeps_full_opacity(self):
        css = (TOKENS.parent / "ds-components.css").read_text(encoding="utf-8")
        rule = re.search(r"\.form-control::placeholder\s*\{([^}]*)\}", css).group(1)
        self.assertIn("opacity: 1", rule)  # o padrão de alguns navegadores (0,54) e o antigo .8 reprovavam

    def test_templates_do_not_use_fixed_color_backgrounds(self):
        """``bg-primary text-white`` e afins ignoram o tema; ``text-bg-*`` segue o design system."""
        root = Path(settings.BASE_DIR) / "templates"
        bad = [str(p.relative_to(root)) for p in root.rglob("*.html")
               if re.search(r'class="[^"]*(?<![\w-])bg-(primary|info|warning|danger|secondary)\b',
                            p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [])

"""Gera static/icons/sprite.svg a partir dos SVGs do Lucide (licença ISC).

Uso (só quando for acrescentar um ícone; a plataforma usa o sprite pronto):

    1. npm pack lucide-static  (numa pasta vazia, fora do projeto)
    2. tar -xzf lucide-static-*.tgz
    3. python tools/build_icon_sprite.py <pasta>/package/icons

O sprite é um único arquivo servido pelo próprio servidor da escola, guardado
em cache pelo navegador: nenhum ícone vem de fora (ver ContentSecurityPolicy).
Para usar um ícone num template: ``{% load ui %}{% icon "house" %}``.
"""

import re
import sys
from pathlib import Path

ICONS = """
house calendar-days layout-dashboard users user-round graduation-cap book-open
notebook-pen clipboard-list clipboard-check users-round list-checks
message-circle megaphone inbox bell file-text chart-column chart-line settings
shield search menu panel-left sun moon log-out key-round chevron-right
chevron-down x plus star clock history keyboard circle-help triangle-alert
check school building-2 link id-card user-check file-check flag eye
heart-handshake arrow-left filter download printer sliders-horizontal
calendar-check layers user-cog circle-check circle-alert info sparkles
book-marked pencil ban paperclip arrow-right corner-down-left
""".split()

DEST = Path(__file__).resolve().parent.parent / "static" / "icons" / "sprite.svg"


def main(src_dir):
    src = Path(src_dir)
    symbols = []
    for name in ICONS:
        svg = (src / f"{name}.svg").read_text(encoding="utf-8")
        inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
        inner = re.sub(r"\s+", " ", inner).strip()
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner}</symbol>')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(
        "<!-- Ícones Lucide (https://lucide.dev), licença ISC: ver LICENSE-lucide.txt -->\n"
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n'
        + "\n".join(symbols)
        + "\n</svg>\n",
        encoding="utf-8",
    )
    print(f"{len(symbols)} ícones em {DEST}")


if __name__ == "__main__":
    main(sys.argv[1])

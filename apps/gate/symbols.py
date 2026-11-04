"""Código de barras (Code 128) e QR Code gerados no servidor, em Python puro, como SVG.

Sem biblioteca nem serviço externo (custo zero; CSP só com 'self'). Os dois formatos são padrões abertos:

- **Code 128, conjunto B** (ISO/IEC 15417): lido por qualquer leitor USB comum, que "digita" o código no
  campo da tela da portaria, seguido de Enter.
- **QR Code** (ISO/IEC 18004): modo byte, correção de erro nível M (recupera cerca de 15% de danos,
  bom para cartão que vai na mochila), versões 1 a 10, Reed–Solomon em GF(256) com o polinômio 0x11D e
  escolha da máscara pela penalidade da norma.

A leitura dos dois foi conferida com um decodificador independente (zxing-cpp) nos testes de
desenvolvimento; ver ``docs/CARTEIRINHA_E_PORTARIA.md``.
"""

from django.utils.html import escape
from django.utils.safestring import mark_safe

# --------------------------------------------------------------------------- Code 128

CODE128 = [
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212", "221213",
    "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221", "223211", "221132",
    "221231", "213212", "223112", "312131", "311222", "321122", "321221", "312212", "322112", "322211",
    "212123", "212321", "232121", "111323", "131123", "131321", "112313", "132113", "132311", "211313",
    "231113", "231311", "112133", "112331", "132131", "113123", "113321", "133121", "313121", "211331",
    "231131", "213113", "213311", "213131", "311123", "311321", "331121", "312113", "312311", "332111",
    "314111", "221411", "431111", "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111",
    "111242", "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311", "113141",
    "114131", "311141", "411131", "211412", "211214", "211232", "2331112",
]
START_B, STOP = 104, 106


def code128_widths(text):
    """Larguras alternadas (barra, espaço, barra…) em módulos, com início, verificação e fim."""
    if not text or any(not 32 <= ord(c) <= 126 for c in text):
        raise ValueError("Code 128-B aceita só ASCII imprimível.")
    values = [START_B] + [ord(c) - 32 for c in text]
    check = (values[0] + sum(i * v for i, v in enumerate(values[1:], start=1))) % 103
    return [int(w) for v in values + [check, STOP] for w in CODE128[v]]


def code128_svg(text, height=48, module=2, quiet=10, label=True):
    widths = code128_widths(text)
    total = (sum(widths) + 2 * quiet) * module
    text_h = 16 if label else 0
    x, bars = quiet * module, []
    for i, w in enumerate(widths):
        if i % 2 == 0:
            bars.append(f'<rect x="{x}" y="0" width="{w * module}" height="{height}"/>')
        x += w * module
    caption = (f'<text x="{total / 2}" y="{height + 13}" text-anchor="middle" class="card-code-text">'
               f'{escape(text)}</text>') if label else ""
    return mark_safe(
        f'<svg viewBox="0 0 {total} {height + text_h}" class="barcode" role="img" '
        f'aria-label="Código de barras {escape(text)}" shape-rendering="crispEdges">'
        f'<rect width="{total}" height="{height + text_h}" fill="#fff"/><g fill="#000">{"".join(bars)}</g>'
        f"{caption}</svg>")


# --------------------------------------------------------------------------- QR Code

# Nível M, versões 1–10: (codewords de correção por bloco, [(blocos, codewords de dados por bloco)])
QR_M = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
         9: [6, 26, 46], 10: [6, 28, 50]}
REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
EC_M_FORMAT = 0  # bits de formato do nível M


def _gf_mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _codewords(payload):
    """(versão, codewords finais intercalados) para os bytes ``payload``."""
    for version in range(1, 11):
        ec_len, groups = QR_M[version]
        capacity = sum(n * size for n, size in groups)
        count_bits = 8 if version < 10 else 16
        if 4 + count_bits + 8 * len(payload) <= capacity * 8:
            break
    else:
        raise ValueError("Conteúdo grande demais para o QR Code (até a versão 10).")
    bits = [0, 1, 0, 0] + [(len(payload) >> i) & 1 for i in reversed(range(count_bits))]
    for byte in payload:
        bits += [(byte >> i) & 1 for i in reversed(range(8))]
    bits += [0] * min(4, capacity * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(data) < capacity:
        data.append(pad[(len(data) - len(bits) // 8) % 2])
    divisor = _rs_divisor(ec_len)
    blocks, k = [], 0
    for n, size in groups:
        for _ in range(n):
            chunk = data[k:k + size]
            k += size
            blocks.append((chunk, _rs_remainder(chunk, divisor)))
    out = []
    for i in range(max(len(b[0]) for b in blocks)):
        out += [b[0][i] for b in blocks if i < len(b[0])]
    for i in range(ec_len):
        out += [b[1][i] for b in blocks]
    return version, out


MASKS = [
    lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0, lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0, lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
]


class _Matrix:
    def __init__(self, version):
        self.version = version
        self.size = 17 + 4 * version
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.mod[y][x] = dark
        self.fn[y][x] = True

    def function_patterns(self):
        s = self.size
        for i in range(s):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = ALIGN[self.version]
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format_bits(0)  # reserva; o valor certo entra depois da máscara
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a, b = s - 11 + i % 3, i // 3
                self.set_fn(a, b, dark)
                self.set_fn(b, a, dark)

    def format_bits(self, mask):
        data = EC_M_FORMAT << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        s = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, s - 15 + i, bit(i))
        self.set_fn(8, s - 8, True)  # módulo escuro fixo

    def place(self, codewords):
        s, i = self.size, 0
        bits = len(codewords) * 8
        right = s - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = s - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < bits:
                        self.mod[y][x] = (codewords[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def masked(self, mask):
        f = MASKS[mask]
        return [[self.mod[y][x] ^ (not self.fn[y][x] and f(x, y)) for x in range(self.size)]
                for y in range(self.size)]


def _penalty(m):
    """Regras 1, 2 e 4 da norma (sequências, blocos 2×2 e equilíbrio claro/escuro)."""
    s, score = len(m), 0
    for lines in (m, [list(c) for c in zip(*m)]):
        for row in lines:
            run = 1
            for a, b in zip(row, row[1:]):
                if a == b:
                    run += 1
                else:
                    score += run - 2 if run >= 5 else 0
                    run = 1
            score += run - 2 if run >= 5 else 0
    for y in range(s - 1):
        for x in range(s - 1):
            if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                score += 3
    dark = sum(sum(r) for r in m)
    score += abs(dark * 20 - s * s * 10) // (s * s) * 10
    return score


def qr_matrix(text):
    version, codewords = _codewords(text.encode("utf-8"))
    best, best_score = None, None
    for mask in range(8):
        mt = _Matrix(version)
        mt.function_patterns()
        mt.place(codewords)
        mt.format_bits(mask)
        m = mt.masked(mask)
        score = _penalty(m)
        if best_score is None or score < best_score:
            best, best_score = m, score
    return best


def qr_svg(text, module=4, quiet=4, label=""):
    m = qr_matrix(text)
    n = len(m) + 2 * quiet
    path = "".join(f"M{x + quiet},{y + quiet}h1v1h-1z" for y, row in enumerate(m) for x, dark in enumerate(row)
                   if dark)
    return mark_safe(
        f'<svg viewBox="0 0 {n} {n}" width="{n * module}" height="{n * module}" class="qrcode" role="img" '
        f'aria-label="{escape(label or "QR Code")}" shape-rendering="crispEdges">'
        f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')

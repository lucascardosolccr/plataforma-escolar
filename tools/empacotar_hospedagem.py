"""Gera o pacote para publicar a plataforma numa hospedagem (ver deploy/pythonanywhere/LEIA-ME.md).

    .venv\\Scripts\\python.exe tools\\empacotar_hospedagem.py

Sai em ``../hospedagem/plataforma-escolar.zip`` só com o código. Ficam de fora, de propósito:
o banco (``db.sqlite3``), os backups, as fotos e os anexos (``media/``), a chave secreta, o ``.env``,
os registros (``logs/``), o ambiente virtual e os caches. A hospedagem começa com banco novo: nenhum dado
de estudante sai deste computador pelo pacote.
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "hospedagem" / "plataforma-escolar.zip"
SKIP_DIRS = {".venv", "venv", "backups", "media", "logs", "staticfiles", "__pycache__", ".git", ".pytest_cache",
             "node_modules"}
SKIP_FILES = {"db.sqlite3", ".secret_key", ".env"}
SKIP_SUFFIXES = (".sqlite3", ".sqlite3-journal", ".pyc", ".log")


def wanted(path):
    rel = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in rel.parts):
        return False
    return path.name not in SKIP_FILES and not path.name.endswith(SKIP_SUFFIXES)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and wanted(p))
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            arcname = str(Path("plataforma-escolar") / p.relative_to(ROOT))
            if p.suffix == ".sh":  # o bash da hospedagem não aceita CRLF, que o Git no Windows pode ter posto
                z.writestr(zipfile.ZipInfo.from_file(p, arcname), p.read_bytes().replace(b"\r\n", b"\n"),
                           compress_type=zipfile.ZIP_DEFLATED)
            else:
                z.write(p, arcname)
    names = zipfile.ZipFile(OUT).namelist()
    leaked = [n for n in names if n.endswith(("db.sqlite3", ".secret_key", "/.env")) or "/media/" in n
              or "/backups/" in n]
    if leaked:
        OUT.unlink()
        sys.exit(f"Pacote recusado: arquivos que não podem sair: {leaked[:5]}")
    print(f"{OUT} — {len(names)} arquivos, {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()

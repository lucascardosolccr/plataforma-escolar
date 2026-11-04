#!/bin/bash
# Atualiza o código no PythonAnywhere depois de enviar um pacote novo (plataforma-escolar.zip) para a pasta inicial:
#     bash ~/plataforma-escolar/deploy/pythonanywhere/atualizar.sh
# Faz backup do banco antes, troca só o código (banco, .env, chave, fotos e backups ficam) e recarrega o site.
set -euo pipefail

APP="$HOME/plataforma-escolar"
VENV="$HOME/.virtualenvs/escola"
ZIP="$HOME/plataforma-escolar.zip"
[ -f "$ZIP" ] || { echo "Envie o plataforma-escolar.zip para $HOME (aba Files) e rode de novo."; exit 1; }

cd "$APP"
echo "== Backup do banco antes de atualizar"
"$VENV/bin/python" manage.py backupdb --manter 5

echo "== Trocando o código"
TMP="$(mktemp -d)"
unzip -q "$ZIP" -d "$TMP"
# O pacote não traz banco, .env, chave, fotos nem backups (tools/empacotar_hospedagem.py recusa se trouxer).
cp -a "$TMP/plataforma-escolar/." "$APP/"
rm -rf "$TMP"
find "$APP" -name "__pycache__" -type d -prune -exec rm -rf {} +

"$VENV/bin/pip" install --quiet -r requirements.txt
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py check --deploy --fail-level ERROR

WSGI="$(ls /var/www/*_wsgi.py 2>/dev/null | head -1 || true)"
if [ -n "$WSGI" ]; then touch "$WSGI"; echo "== Site recarregado ($WSGI)"; else echo "== Clique em Reload na aba Web."; fi
rm -f "$ZIP"
echo "== Atualizado."

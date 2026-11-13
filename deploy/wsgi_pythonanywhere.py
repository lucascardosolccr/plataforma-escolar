# Conteúdo para o arquivo WSGI do PythonAnywhere.
# No painel Web do PythonAnywhere há um link "WSGI configuration file"
# (algo como /var/www/SEU_USUARIO_pythonanywhere_com_wsgi.py).
# APAGUE todo o conteúdo dele e cole ISTO, trocando SEU_USUARIO.
#
# Não é preciso definir variáveis de ambiente aqui: o settings carrega o
# arquivo .env da raiz do projeto sozinho (DEBUG, ALLOWED_HOSTS, SSL, etc.).

import sys

path = "/home/SEU_USUARIO/plataforma-escolar"
if path not in sys.path:
    sys.path.insert(0, path)

import os
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

# Conteúdo para o arquivo WSGI do PythonAnywhere (aba Web → "WSGI configuration file").
# Apague tudo o que estiver lá e cole este texto. Troque USUARIO pelo seu nome de usuário do PythonAnywhere.
# As configurações (DEBUG desligado, endereços, HTTPS) vêm do arquivo .env criado por instalar.sh.
import os
import sys

path = "/home/USUARIO/plataforma-escolar"
if path not in sys.path:
    sys.path.insert(0, path)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()

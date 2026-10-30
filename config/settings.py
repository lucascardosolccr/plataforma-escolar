"""
Configurações do projeto Plataforma Escolar Integrada — custo zero.

Variáveis do ambiente (arquivo .env na raiz do projeto):
  DJANGO_SECRET_KEY   chave secreta (gerada automaticamente no 1º uso, se ausente)
  DJANGO_DEBUG        "1" ativa depuração, qualquer outro valor desativa
  DJANGO_ALLOWED_HOSTS  hosts permitidos separados por vírgula (vazio = localhost)
  DJANGO_LANG         pt-br
  DJANGO_TZ           America/Sao_Paulo
  DJANGO_SESSION_HOURS  horas sem uso até sair da conta (padrão 8)
  DJANGO_SESSION_KEEP   "1" mantém o login depois de fechar o navegador
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(BASE_DIR / ".env")


def _secret_key() -> str:
    key = os.environ.get("DJANGO_SECRET_KEY", "")
    if key:
        return key
    from django.core.management.utils import get_random_secret_key

    key_file = BASE_DIR / ".secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = get_random_secret_key()
    key_file.write_text(key, encoding="utf-8")
    try:
        import git  # noqa: F401
    except ImportError:
        pass
    return key


SECRET_KEY = _secret_key()

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
    if h.strip()
] or ["127.0.0.1", "localhost"]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.academics",
    "apps.registry",
    "apps.pedagogy",
    "apps.communication",
    "apps.analytics",
    "apps.school_calendar",
    "apps.rotina",
    "apps.coordination",
    "apps.printing",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    # Depois da autenticação: precisa de request.user resolvido.
    "apps.core.middleware.ForcePasswordChangeMiddleware",
    "apps.core.middleware.ScheduledPublicationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.ContentSecurityPolicyMiddleware",
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.core.context_processors.platform_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = os.environ.get("DJANGO_LANG", "pt-br")
TIME_ZONE = os.environ.get("DJANGO_TZ", "America/Sao_Paulo")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "core.User"

LOGIN_URL = "login"

SESSION_COOKIE_HTTPONLY = True
# Sessão curta: a plataforma roda em computadores compartilhados da escola e
# guarda dados de crianças. O padrão do Django mantinha o login por 2 semanas,
# mesmo com o navegador fechado. Agora: sai ao fechar o navegador e depois de
# 8 horas sem uso (o prazo recomeça a cada página aberta).
SESSION_COOKIE_AGE = int(os.environ.get("DJANGO_SESSION_HOURS", "8")) * 3600
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = os.environ.get("DJANGO_SESSION_KEEP", "0") != "1"
CSRF_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# Proteções que só fazem sentido sob HTTPS. Ficam atrás de DJANGO_SSL porque
# ativá-las em HTTP (o caso da escola que roda na rede local) faria o
# navegador deixar de enviar os cookies de sessão e de CSRF, impedindo o
# login. Em HTTPS, defina DJANGO_SSL=1 e todas passam a valer juntas.
_SSL = os.environ.get("DJANGO_SSL", "0") == "1"

if not DEBUG and _SSL:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000  # 1 ano
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Nível do Django -> cor do alerta do Bootstrap. O mapa anterior estava
# deslocado um nível: sucesso aparecia amarelo e aviso aparecia como erro.
MESSAGE_TAGS = {
    10: "secondary",  # DEBUG
    20: "info",  # INFO
    25: "success",  # SUCCESS
    30: "warning",  # WARNING
    40: "danger",  # ERROR
}
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_not_required
from django.urls import include, path, re_path
from django.views.static import serve as static_serve

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.core.urls")),
    path("", include("apps.academics.urls")),
    path("", include("apps.registry.urls")),
    path("", include("apps.pedagogy.urls")),
    path("", include("apps.communication.urls")),
    path("", include("apps.analytics.urls")),
    path("calendario/", include("apps.school_calendar.urls")),
    path("", include("apps.rotina.urls")),
    path("", include("apps.meetings.urls")),
    path("", include("apps.coordination.urls")),
    path("", include("apps.printing.urls")),
    path("", include("apps.curriculum.urls")),
    path("", include("apps.inclusion.urls")),
    path("", include("apps.cognitio.urls")),
]

# O servidor de desenvolvimento (runserver) só serve arquivos estáticos quando
# DEBUG=True. Como a escola opera com DEBUG=0 (padrão seguro), os arquivos em
# static/ (Bootstrap, CSS e JS locais) são servidos por esta rota pública — o
# mesmo domínio de /static/ de sempre.
# Obs.: `login_not_required` é obrigatório, pois o LoginRequiredMiddleware
# redireciona qualquer rota não marcada como pública quando o usuário é anônimo.
if not settings.DEBUG:
    serve_public_static = login_not_required(static_serve)
    urlpatterns += [
        re_path(
            r"^static/(?P<path>.*)$",
            serve_public_static,
            {"document_root": settings.STATICFILES_DIRS[0]},
        ),
    ]

# NOTA: arquivos de mídia (fotos/documentos) NÃO são servidos por URL pública.
# Eles são acessados somente por views autenticadas (ex.: registry.views.student_photo),
# com verificação de permissão no servidor — requisito do projeto (seção 11).
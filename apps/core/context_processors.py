from django.conf import settings

from .models import Role


def platform_context(request):
    user = request.user
    ctx = {
        "ROLE_ADMIN": Role.ADMIN.value,
        "ROLE_DIRECAO": Role.DIRECAO.value,
        "ROLE_COORDENACAO": Role.COORDENACAO.value,
        "ROLE_SECRETARIA": Role.SECRETARIA.value,
        "ROLE_PROFESSOR": Role.PROFESSOR.value,
        "ROLE_RESPONSAVEL": Role.RESPONSAVEL.value,
        "ROLE_ESTUDANTE": Role.ESTUDANTE.value,
        "theme": "dark" if request.COOKIES.get("theme") == "dark" else "light",
        # Barra lateral recolhida (só ícones) lembrada por cookie, para a página
        # já vir no estado certo, sem "piscar".
        "sidebar_rail": request.COOKIES.get("sidebar") == "rail",
        "hosting_provider": settings.HOSTING_PROVIDER,
    }
    if user.is_authenticated:
        ctx["user_role"] = user.role
        ctx["user_role_label"] = user.role_label
        ctx["user_is_staff"] = user.is_staff_role
        from . import navigation

        match = getattr(request, "resolver_match", None)
        ctx["nav"] = navigation.build(user, match.view_name if match else None)
        from .models import UserPreference

        pref = UserPreference.objects.filter(user=user).first()
        ctx["user_prefs"] = pref.as_json() if pref else {"saved": False, "favorites": [], "filters": []}
        if user.role == Role.ESTUDANTE.value:
            ctx["own_student"] = getattr(user, "student_record", None)
        if user.school_id is not None:
            from apps.communication.models import Notification

            ctx["unread_notifications"] = Notification.objects.filter(
                user=user, is_read=False
            ).count()
    return ctx
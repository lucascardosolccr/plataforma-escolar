from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import create_audit_log


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    create_audit_log(user=user, action="login", request=request, detail="Login realizado")


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        create_audit_log(user=user, action="logout", request=request, detail="Logout realizado")


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request, **kwargs):
    username = credentials.get("username", "")
    create_audit_log(
        user=None,
        action="login_failed",
        request=request,
        detail=f"Falha de login para: {username}",
    )
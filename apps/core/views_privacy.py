"""Privacidade: controlador, encarregado (LGPD, art. 41) e como a família exerce os direitos do art. 18.

A página é pública: o art. 41, § 1º, pede que a identidade e o contato do encarregado sejam divulgados
publicamente, de forma clara. Só a direção e a administração editam, e cada alteração fica na auditoria.
"""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_not_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .models import PrivacyContact, Role, create_audit_log

EDITORS = (Role.DIRECAO.value, Role.ADMIN.value)


class PrivacyContactForm(forms.ModelForm):
    class Meta:
        model = PrivacyContact
        fields = ["controller", "officer_name", "officer_email", "officer_phone", "channel", "responders"]
        widgets = {"channel": forms.Textarea(attrs={"rows": 3})}


def can_edit(user):
    return user.is_authenticated and user.role in EDITORS and user.school_id is not None


def contact_for(school):
    return PrivacyContact.objects.filter(school=school).first() if school else None


@login_not_required
def privacy_page(request):
    user = request.user
    own = contact_for(user.school) if user.is_authenticated else None
    others = PrivacyContact.objects.select_related("school").order_by("school__name")
    if own:
        others = others.exclude(pk=own.pk)
    return render(request, "core/privacy.html", {
        "layout": "base.html" if user.is_authenticated else "auth_base.html", "own": own,
        "contacts": list(others), "can_edit": can_edit(user),
        "is_family": user.is_authenticated and user.role == Role.RESPONSAVEL.value,
    })


def privacy_edit(request):
    user = request.user
    if not can_edit(user):
        raise PermissionDenied
    instance = contact_for(user.school) or PrivacyContact(school=user.school)
    form = PrivacyContactForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.updated_by = user
        contact.save()
        create_audit_log(user=user, action="update", request=request, target=contact,
                         detail=f"Atualizou o encarregado de dados: {contact.officer_name}")
        messages.success(request, "Dados do encarregado publicados na página de privacidade.")
        return redirect("privacy")
    return render(request, "core/privacy_form.html", {"form": form})

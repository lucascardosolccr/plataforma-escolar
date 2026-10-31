from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def learning_summary_url(context, student):
    """Endereço do resumo de aprendizagens, se a escola o liberou e a pessoa pode ver."""
    from apps.cognitio.views_family import family_can_view

    request = context.get("request")
    if request is None or not family_can_view(request.user, student):
        return ""
    return reverse("cognitio:family_summary", args=[student.pk])

"""Achados e perdidos.

A escola registra o objeto (o que é, onde e quando foi achado, foto opcional só do objeto). A família vê o que está
guardado e diz "é meu", descrevendo um detalhe; a escola confere e registra a entrega. Celular, fone, documento,
cartão e chave aparecem sem detalhes nem foto para as famílias: quem é dono descreve, quem não é não tem como
copiar a descrição.
"""

import os
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import School
from apps.core.uploads import ALLOWED_PHOTO_EXTENSIONS, validate_photo

#: Depois de tantos dias guardado, o objeto aparece em "Pode doar".
DONATE_AFTER_DAYS = 60
#: As famílias veem o que foi achado nos últimos tantos dias.
FAMILY_WINDOW_DAYS = 90


def item_photo_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"achados/{uuid.uuid4().hex}{ext if ext in ALLOWED_PHOTO_EXTENSIONS else '.jpg'}"


class FoundItem(models.Model):
    class Category(models.TextChoices):
        CLOTHES = "roupa", "Roupa, agasalho e calçado"
        BOTTLE = "lancheira", "Garrafa, lancheira e pote"
        SUPPLIES = "material", "Material escolar, estojo e mochila"
        GLASSES = "oculos", "Óculos, relógio e acessórios"
        TOY = "brinquedo", "Brinquedo e material de esporte"
        ELECTRONIC = "eletronico", "Celular, fone e eletrônicos"
        DOCUMENT = "documento", "Documento, cartão e chave"
        OTHER = "outro", "Outro"

    #: Detalhes e foto ficam só com a escola: o dono precisa descrever.
    VALUABLE = (Category.ELECTRONIC, Category.DOCUMENT)

    class Status(models.TextChoices):
        KEPT = "guardado", "Guardado"
        RETURNED = "devolvido", "Entregue ao dono"
        DONATED = "doado", "Doado ou descartado"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="found_items")
    title = models.CharField("o que é", max_length=120, help_text="Ex.: casaco azul-marinho, garrafa rosa.")
    category = models.CharField("tipo", max_length=12, choices=Category.choices, default=Category.CLOTHES)
    details = models.CharField(
        "detalhes", max_length=300, blank=True,
        help_text="Marca, tamanho, estampa, nome escrito. Celular, fone, documento e chave: as famílias não veem.")
    place = models.CharField("onde foi achado", max_length=120, blank=True, help_text="Ex.: quadra, pátio, sala 3.")
    found_on = models.DateField("achado em", default=timezone.localdate)
    photo = models.ImageField("foto do objeto (opcional)", upload_to=item_photo_path, validators=[validate_photo],
                              null=True, blank=True,
                              help_text="Só o objeto: sem pessoas, sem documento aberto, sem tela de celular.")
    student = models.ForeignKey("registry.Student", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="found_items", verbose_name="dono identificado")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.KEPT)
    returned_to = models.CharField("entregue a", max_length=120, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+")
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                      related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-found_on", "-pk"]
        indexes = [models.Index(fields=["school", "status", "found_on"])]
        verbose_name = "objeto achado"
        verbose_name_plural = "achados e perdidos"

    def __str__(self):
        return self.title

    @property
    def valuable(self):
        return self.category in self.VALUABLE

    def days_kept(self, today=None):
        return ((today or timezone.localdate()) - self.found_on).days


class Claim(models.Model):
    """"É meu": quem reconhece o objeto descreve um detalhe; a escola confere antes de entregar."""

    class Status(models.TextChoices):
        PENDING = "pendente", "Aguardando a escola"
        ACCEPTED = "confirmado", "Confirmado e entregue"
        REJECTED = "recusado", "Não confere"

    item = models.ForeignKey(FoundItem, on_delete=models.CASCADE, related_name="claims")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    student = models.ForeignKey("registry.Student", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="+", verbose_name="de quem é")
    description = models.CharField("como você reconhece", max_length=300)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "pedido de objeto"
        verbose_name_plural = "pedidos de objetos"

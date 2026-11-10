"""Biblioteca escolar: o acervo, quem está com cada livro, até quando, e a fila de quem espera.

Disponíveis = exemplares − emprestados − separados para quem reservou. Ninguém fica com dois exemplares do mesmo
livro, e quem tem livro atrasado só pega outro depois de devolver (``services``).
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.core.models import School


class LibrarySettings(models.Model):
    """Regras da biblioteca da escola e quem opera o balcão além da gestão."""

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="library_settings")
    loan_days = models.PositiveSmallIntegerField(
        "dias de empréstimo", default=14, validators=[MinValueValidator(1), MaxValueValidator(60)],
        help_text="Se a devolução cair em fim de semana, feriado ou férias, passa para o próximo dia letivo.")
    max_loans = models.PositiveSmallIntegerField(
        "livros ao mesmo tempo por estudante", default=2, validators=[MinValueValidator(1), MaxValueValidator(10)])
    max_renewals = models.PositiveSmallIntegerField(
        "renovações permitidas", default=1, validators=[MaxValueValidator(5)],
        help_text="A família ou o estudante renovam pela plataforma, se ninguém estiver na fila do livro.")
    hold_days = models.PositiveSmallIntegerField(
        "dias para retirar um livro reservado", default=3, validators=[MinValueValidator(1), MaxValueValidator(10)])
    librarians = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="+", verbose_name="quem cuida da biblioteca",
        help_text="Além da direção, coordenação e secretaria: professores ou funcionários que fazem empréstimos.")

    class Meta:
        verbose_name = "regras da biblioteca"
        verbose_name_plural = "regras da biblioteca"


class Book(models.Model):
    class Category(models.TextChoices):
        CHILDREN = "infantil", "Literatura infantil"
        YOUTH = "juvenil", "Literatura juvenil"
        FICTION = "literatura", "Literatura (adulto e clássicos)"
        COMICS = "hq", "Quadrinhos e mangá"
        POETRY = "poesia", "Poesia e teatro"
        NONFICTION = "informativo", "Informativos (ciência, história, biografias)"
        TEXTBOOK = "didatico", "Didáticos e paradidáticos"
        REFERENCE = "referencia", "Dicionários e referência"
        OTHER = "outro", "Outro"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="books")
    title = models.CharField("título", max_length=200)
    author = models.CharField("autor(es)", max_length=150, blank=True)
    category = models.CharField("tipo", max_length=12, choices=Category.choices, default=Category.CHILDREN)
    publisher = models.CharField("editora", max_length=100, blank=True)
    year = models.PositiveSmallIntegerField("ano", null=True, blank=True,
                                            validators=[MinValueValidator(1450), MaxValueValidator(2100)])
    isbn = models.CharField("ISBN", max_length=20, blank=True)
    copies = models.PositiveSmallIntegerField("exemplares", default=1,
                                              validators=[MinValueValidator(1), MaxValueValidator(500)])
    location = models.CharField("estante ou caixa", max_length=60, blank=True)
    summary = models.TextField("sinopse (opcional)", blank=True, max_length=1500)
    active = models.BooleanField("no acervo", default=True,
                                 help_text="Desmarque para dar baixa (perdido, doado, estragado). O histórico fica.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["title", "author"]
        indexes = [models.Index(fields=["school", "title"])]
        verbose_name = "livro"
        verbose_name_plural = "livros"

    def __str__(self):
        return f"{self.title} ({self.author})" if self.author else self.title


class Loan(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="loans")
    book = models.ForeignKey(Book, on_delete=models.PROTECT, related_name="loans", verbose_name="livro")
    student = models.ForeignKey("registry.Student", on_delete=models.PROTECT, related_name="loans",
                                verbose_name="estudante")
    lent_at = models.DateTimeField("emprestado em", default=timezone.now)
    due_on = models.DateField("devolver até")
    renewals = models.PositiveSmallIntegerField("renovações", default=0)
    returned_at = models.DateTimeField("devolvido em", null=True, blank=True)
    condition_note = models.CharField("estado na devolução", max_length=200, blank=True)
    lent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")

    class Meta:
        ordering = ["due_on", "pk"]
        indexes = [models.Index(fields=["school", "returned_at", "due_on"])]
        verbose_name = "empréstimo"
        verbose_name_plural = "empréstimos"

    def __str__(self):
        return f"{self.book} com {self.student}"

    @property
    def open(self):
        return self.returned_at is None

    def days_late(self, today=None):
        if self.returned_at is not None:
            return 0
        return max(0, ((today or timezone.localdate()) - self.due_on).days)


class Reservation(models.Model):
    """Fila de quem quer um livro sem exemplar livre. Quando um volta, o primeiro da fila tem alguns dias para
    retirar; se não retirar, a vez passa ao próximo."""

    class Status(models.TextChoices):
        WAITING = "aguardando", "Na fila"
        READY = "separado", "Separado para retirar"
        DONE = "atendida", "Retirado"
        CANCELED = "cancelada", "Cancelada"
        EXPIRED = "expirada", "Não retirado no prazo"

    OPEN = (Status.WAITING, Status.READY)

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="book_reservations")
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reservations", verbose_name="livro")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="book_reservations",
                                verbose_name="estudante")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.WAITING)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    ready_on = models.DateField("separado em", null=True, blank=True)
    expires_on = models.DateField("retirar até", null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "reserva de livro"
        verbose_name_plural = "reservas de livros"

    def __str__(self):
        return f"{self.book} para {self.student}"

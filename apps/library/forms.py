from django import forms

from apps.core.models import Role, User

from .models import Book, LibrarySettings


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ["title", "author", "category", "copies", "location", "publisher", "year", "isbn", "summary",
                  "active"]
        widgets = {"summary": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        if not self.instance.pk:
            del self.fields["active"]

    def clean_title(self):
        return " ".join(self.cleaned_data["title"].split())

    def clean(self):
        c = super().clean()
        title, author = c.get("title"), (c.get("author") or "").strip()
        if title:
            qs = Book.objects.filter(school=self.school, title__iexact=title, author__iexact=author)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Este livro já está no acervo. Aumente o número de exemplares dele.")
        if self.instance.pk and c.get("copies"):
            lent = self.instance.loans.filter(returned_at__isnull=True).count()
            if c["copies"] < lent:
                self.add_error("copies", f"Há {lent} exemplar(es) emprestado(s) agora.")
        return c


class SettingsForm(forms.ModelForm):
    class Meta:
        model = LibrarySettings
        fields = ["loan_days", "max_loans", "max_renewals", "hold_days", "librarians"]
        widgets = {"librarians": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["librarians"].queryset = User.objects.filter(
            school=school, is_active=True, role=Role.PROFESSOR.value).order_by("first_name", "username")
        self.fields["librarians"].label_from_instance = lambda u: u.get_full_name() or u.username
        self.fields["librarians"].label = "Professores que também operam o balcão"


class ImportForm(forms.Form):
    file = forms.FileField(label="Planilha (CSV)", help_text="Colunas: título; autor; exemplares; tipo; estante; "
                                                             "editora; ano; ISBN. Só o título é obrigatório.")

from django import forms
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear

from .models import SupplyItem, SupplyList


class ListForm(forms.ModelForm):
    class Meta:
        model = SupplyList
        fields = ["title", "school_year", "grade", "class_groups", "deliver_by", "intro"]
        widgets = {"deliver_by": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "intro": forms.Textarea(attrs={"rows": 4}), "class_groups": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        open_years = Q(end_date__isnull=True) | Q(end_date__gte=today) | Q(is_current=True)
        if self.instance.pk:
            open_years |= Q(pk=self.instance.school_year_id)
        years = SchoolYear.objects.filter(school=school).filter(open_years).order_by("name")
        self.fields["school_year"].queryset = years
        self.fields["class_groups"].queryset = ClassGroup.objects.filter(
            school=school, school_year__in=years).order_by("school_year__name", "name")
        if not self.instance.pk:
            current = years.filter(is_current=True).first()
            if current:
                self.fields["school_year"].initial = current.pk

    def clean_deliver_by(self):
        day = self.cleaned_data.get("deliver_by")
        if day and day < timezone.localdate() and "deliver_by" in self.changed_data:
            raise forms.ValidationError("Essa data já passou.")
        return day

    def clean(self):
        c = super().clean()
        year, classes = c.get("school_year"), c.get("class_groups") or []
        if year and any(cg.school_year_id != year.pk for cg in classes):
            self.add_error("class_groups", f"Escolha só turmas de {year}.")
        return c


class ItemForm(forms.ModelForm):
    class Meta:
        model = SupplyItem
        fields = ["quantity", "unit", "name", "notes", "optional"]


class PasteForm(forms.Form):
    texto = forms.CharField(label="Cole a lista", max_length=12000, widget=forms.Textarea(attrs={"rows": 8}),
                            help_text="Uma linha por material, com a quantidade no começo: “2 cadernos de 96 folhas”, "
                                      "“1 caixa de lápis de cor (opcional)”. Numeração como “3)” é ignorada.")

from django import forms

from apps.academics.models import ClassGroup

from .models import SchoolGoal


class GoalForm(forms.ModelForm):
    class Meta:
        model = SchoolGoal
        fields = ["indicator", "class_group", "target", "starts_on", "deadline", "title", "notes"]
        widgets = {
            "starts_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "deadline": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "target": "Frequência, entregas e habilidades em %, de 0 a 100. Média geral na escala das notas.",
            "starts_on": "O resultado é calculado deste dia até hoje (ou até o prazo).",
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["class_group"].queryset = ClassGroup.objects.filter(
            school=school, school_year__is_current=True).order_by("name")
        self.fields["class_group"].empty_label = "A escola toda"

    def clean(self):
        data = super().clean()
        start, end, target = data.get("starts_on"), data.get("deadline"), data.get("target")
        if start and end and end <= start:
            self.add_error("deadline", "O prazo precisa ser depois do início.")
        if target is not None and not 0 <= target <= 100:
            self.add_error("target", "Use um valor entre 0 e 100.")
        return data

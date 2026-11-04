from django.urls import path

from . import views

app_name = "gate"

urlpatterns = [
    path("carteirinhas/", views.cards_index, name="cards"),
    path("minha-carteirinha/", views.mine, name="mine"),
    path("carteirinha/estudante/<int:student_id>/", views.card_view, name="card"),
    path("carteirinha/estudante/<int:student_id>/emitir/", views.card_issue, name="card_issue"),
    path("carteirinha/turma/<int:class_id>/", views.class_cards, name="class_cards"),
    path("portaria/", views.station, name="station"),
    path("portaria/hoje/", views.today, name="today"),
    path("portaria/horarios/", views.settings_edit, name="settings"),
    path("portaria/estudante/<int:student_id>/", views.history, name="history"),
]

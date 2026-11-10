from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    path("biblioteca-escolar/", views.catalog, name="catalog"),
    path("biblioteca-escolar/livro/novo/", views.book_form, name="book_create"),
    path("biblioteca-escolar/livro/<int:pk>/", views.book_detail, name="book"),
    path("biblioteca-escolar/livro/<int:pk>/editar/", views.book_form, name="book_edit"),
    path("biblioteca-escolar/livro/<int:pk>/emprestar/", views.lend, name="lend"),
    path("biblioteca-escolar/livro/<int:pk>/reservar/", views.reserve, name="reserve"),
    path("biblioteca-escolar/balcao/", views.desk, name="desk"),
    path("biblioteca-escolar/emprestimo/<int:pk>/devolver/", views.give_back, name="give_back"),
    path("biblioteca-escolar/emprestimo/<int:pk>/renovar/", views.renew, name="renew"),
    path("biblioteca-escolar/reserva/<int:pk>/cancelar/", views.cancel_reservation, name="cancel_reservation"),
    path("biblioteca-escolar/meus-livros/", views.mine, name="mine"),
    path("biblioteca-escolar/regras/", views.settings_view, name="settings"),
    path("biblioteca-escolar/importar/", views.import_books, name="import"),
]

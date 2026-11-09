from django.urls import path

from . import views

app_name = "care"

urlpatterns = [
    path("saude-e-retirada/", views.home, name="home"),
    path("saude/estudante/<int:student_id>/", views.health_view, name="health"),
    path("saude/estudante/<int:student_id>/editar/", views.health_edit, name="health_edit"),
    path("saude/turma/<int:class_id>/", views.class_alerts, name="class_alerts"),
    path("saude/alimentacao/", views.food_list, name="food"),
    path("retirada/estudante/<int:student_id>/", views.pickup_student, name="pickups"),
    path("retirada/estudante/<int:student_id>/aviso/", views.notice_create, name="notice_create"),
    path("retirada/estudante/<int:student_id>/registrar/", views.pickup_register, name="register"),
    path("retirada/pessoa/<int:pk>/retirar/", views.pickup_revoke, name="pickup_revoke"),
    path("retirada/aviso/<int:pk>/cancelar/", views.notice_cancel, name="notice_cancel"),
]

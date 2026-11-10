from django.urls import path

from . import views, views_incidents as inc, views_meds as med

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
    path("saude/atendimentos/", inc.incident_list, name="incidents"),
    path("saude/atendimentos/novo/", inc.incident_pick, name="incident_pick"),
    path("saude/atendimentos/estudante/<int:student_id>/novo/", inc.incident_create, name="incident_create"),
    path("saude/atendimentos/<int:pk>/", inc.incident_detail, name="incident"),
    path("saude/atendimentos/<int:pk>/ciente/", inc.incident_ack, name="incident_ack"),
    path("saude/remedios/", med.medication_list, name="medications"),
    path("saude/remedios/hoje/", med.medication_today, name="medication_today"),
    path("saude/remedios/estudante/<int:student_id>/pedir/", med.medication_create, name="medication_create"),
    path("saude/remedios/<int:pk>/", med.medication_detail, name="medication"),
    path("saude/remedios/<int:pk>/analisar/", med.medication_review, name="medication_review"),
    path("saude/remedios/<int:pk>/encerrar/", med.medication_end, name="medication_end"),
    path("saude/remedios/<int:pk>/dose/", med.medication_dose, name="medication_dose"),
    path("saude/remedios/dose/<int:pk>/desfazer/", med.medication_dose_undo, name="medication_dose_undo"),
]

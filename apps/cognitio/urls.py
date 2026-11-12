from django.urls import path

from . import (views, views_agreement, views_dash, views_evidence, views_family, views_intel, views_prescriptive,
               views_projection, views_text, views_trajectory)

app_name = "cognitio"

urlpatterns = [
    path("cognitio/", views.home, name="home"),
    path("cognitio/escala/", views.scale_settings, name="scale"),
    path("cognitio/painel/", views_dash.dashboard, name="dashboard"),
    path("cognitio/concordancia/", views_agreement.observer_agreement, name="agreement"),
    path("cognitio/turma/<int:class_id>/trajetorias/", views_trajectory.class_trajectories, name="class_trajectories"),
    path("cognitio/estudante/<int:student_id>/trajetoria/", views_trajectory.student_trajectory,
         name="student_trajectory"),
    path("cognitio/estudante/<int:student_id>/projecao/", views_projection.student_projection,
         name="student_projection"),
    path("cognitio/estudante/<int:student_id>/decisao/", views_projection.judgment_save, name="judgment_save"),
    path("cognitio/assistente/", views_projection.assistant_page, name="assistant"),
    path("cognitio/minhas-decisoes/", views_projection.my_judgments, name="my_judgments"),
    path("cognitio/turma/<int:class_id>/conselho/", views_projection.class_council, name="class_council"),
    path("aprendizagens/<int:student_id>/", views_family.learning_summary, name="family_summary"),
    path("cognitio/disciplina/", views_dash.discipline, name="discipline"),
    path("cognitio/estudante/<int:student_id>/", views.student_map, name="student_map"),
    path("cognitio/turma/<int:class_id>/", views.class_view, name="class_view"),
    path("cognitio/turma/<int:class_id>/disciplina/<int:subject_id>/observacao/", views_evidence.observation_create,
         name="observation_create"),
    path("cognitio/avaliacao/<int:evaluation_id>/questoes/", views_evidence.questions, name="questions"),
    path("cognitio/avaliacao/<int:evaluation_id>/resultados/", views_evidence.responses, name="responses"),
    path("cognitio/avaliacao/<int:evaluation_id>/analise/", views_evidence.analysis, name="exam_analysis"),
    # Grafo, alertas e modelos
    path("cognitio/habilidade/<int:item_id>/grafo/", views_intel.skill_graph, name="skill_graph"),
    path("cognitio/habilidade/<int:item_id>/grafo/relacao/", views_intel.relation_curate, name="relation_curate"),
    path("cognitio/alertas/", views_intel.alert_list, name="alerts"),
    path("cognitio/alertas/<int:pk>/revisar/", views_intel.alert_review, name="alert_review"),
    path("cognitio/modelos/", views_intel.models_page, name="models"),
    # Intervenções e trilhas
    path("cognitio/intervencoes/", views_prescriptive.intervention_list, name="interventions"),
    path("cognitio/intervencoes/nova/", views_prescriptive.intervention_create, name="intervention_create"),
    path("cognitio/intervencoes/<int:pk>/", views_prescriptive.intervention_detail, name="intervention_detail"),
    path("cognitio/trilha/<int:class_id>/<int:subject_id>/<int:item_id>/", views_prescriptive.trail_create,
         name="trail_create"),
    path("cognitio/estrategias/", views_prescriptive.strategy_bank, name="strategies"),
    # Produções escritas (PLN por regras)
    path("cognitio/producoes/", views_text.text_list, name="texts"),
    path("cognitio/producoes/nova/", views_text.text_create, name="text_create"),
    path("cognitio/producoes/<int:pk>/", views_text.text_detail, name="text_detail"),
]

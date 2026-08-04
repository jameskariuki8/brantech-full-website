from django.urls import path
from editorial import views

urlpatterns = [
    path('dashboard/', views.dashboard_view, name='editorial_dashboard'),
    path('api/run-pipeline/', views.trigger_pipeline_api, name='api_run_pipeline'),
    path('api/pipeline-runs/<int:run_id>/', views.pipeline_run_status_api, name='api_pipeline_run_status'),
    path('api/articles/<int:article_id>/', views.article_detail_api, name='api_article_detail'),
    path('api/articles/<int:article_id>/approve/', views.approve_article_api, name='api_approve_article'),
    path('api/articles/<int:article_id>/reject/', views.reject_article_api, name='api_reject_article'),
    path('api/articles/<int:article_id>/export-docx/', views.export_docx_view, name='export_article_docx'),
    path('api/knowledge-search/', views.semantic_search_api, name='api_semantic_search'),
]

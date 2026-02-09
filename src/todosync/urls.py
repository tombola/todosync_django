from django.urls import path
from . import views

app_name = 'todosync'

urlpatterns = [
    path('create/', views.create_task_group, name='create_task_group'),
]

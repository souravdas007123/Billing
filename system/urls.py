from django.urls import path
from system import views
urlpatterns = [
    path('', views.home,name='home'),
]
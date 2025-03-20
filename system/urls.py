from django.urls import path
from system import views
urlpatterns = [
    path('', views.home,name='home'),
    path('unit/', views.unit,name='unit'),
    path('product/', views.product,name='product'),
    path('vendor/', views.vendor,name='vendor'),
    path('customer/', views.customer,name='customer'),
    path('purchase/', views.purchase,name='purchase'),
    path('sale/', views.sale,name='sale'),
    path('setting/', views.setting,name='setting'),





]
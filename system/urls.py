from django.urls import path
from system import views
urlpatterns = [
    path('', views.home,name='home'),
    path('unit/', views.unit,name='unit'),
    path('unitdata/', views.unit_data,name='unitdata'),
    path('unitadd/', views.unit_add,name='unitadd'),
    path('product/', views.product,name='product'),
    path('productdata/', views.product_data,name='productdata'),
    path('productadd/', views.product_add,name='productadd'),
    path('vendor/', views.vendor,name='vendor'),
    path('vendordata/', views.vendor_data,name='vendordata'),
    path('vendoradd/', views.vendor_add,name='vendoradd'),
    path('customer/', views.customer,name='customer'),
    path('customerdata/', views.customer_data,name='customerdata'),
    path('customeradd/', views.customer_add,name='customeradd'),
    path('purchase/', views.purchase,name='purchase'),
    path('purchasedata/', views.purchase_data,name='purchasedata'),
    path('purchaseadd/', views.purchase_add,name='purchaseadd'),
    path('sale/', views.sale,name='sale'),
    path('saledata/', views.sale_data,name='saledata'),
    path('saleadd/', views.sale_add,name='saleadd'),
    path('setting/', views.setting,name='setting'),





]
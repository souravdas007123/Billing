from django.urls import path

from . import views

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("new/", views.invoice_form, name="invoice_new"),
    path("<int:pk>/edit/", views.invoice_form, name="invoice_edit"),
    path("save/", views.invoice_save, name="invoice_save"),
    path("<int:pk>/save/", views.invoice_save, name="invoice_update"),
    path("calc/", views.calc_api, name="calc_api"),
    path("check-number/", views.check_number, name="check_number"),
    path("<int:pk>/submit/", views.invoice_submit, name="invoice_submit"),
    path("<int:pk>/print/", views.invoice_print, name="invoice_print"),
]

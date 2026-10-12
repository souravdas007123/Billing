from django.urls import path

from . import views

urlpatterns = [
    path("", views.invoice_list, name="invoice_list"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("dashboard/export/", views.dashboard_export, name="dashboard_export"),
    path("gst/", views.gst_reports, name="gst_reports"),
    path("gst/export/<str:kind>/", views.gst_export, name="gst_export"),
    path("statement/", views.party_statement, name="party_statement"),
    path("backup/", views.backup_download, name="backup_download"),
    path("firm-image/<str:kind>/", views.firm_image, name="firm_image"),
    path("new/", views.invoice_form, name="invoice_new"),
    path("<int:pk>/edit/", views.invoice_form, name="invoice_edit"),
    path("save/", views.invoice_save, name="invoice_save"),
    path("<int:pk>/save/", views.invoice_save, name="invoice_update"),
    path("calc/", views.calc_api, name="calc_api"),
    path("check-number/", views.check_number, name="check_number"),
    path("<int:pk>/submit/", views.invoice_submit, name="invoice_submit"),
    path("<int:pk>/cancel/", views.invoice_cancel, name="invoice_cancel"),
    path("<int:pk>/delete-draft/", views.invoice_delete_draft, name="invoice_delete_draft"),
    path("<int:pk>/print/", views.invoice_print, name="invoice_print"),
]

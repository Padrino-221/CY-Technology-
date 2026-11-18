from django.contrib.auth import views as auth
from django.contrib.auth.decorators import login_required
from django.urls import path
from django.views.generic import TemplateView
from credit import views
import offline

urlpatterns = [
    path("offline-worker.js", offline.worker),
    path("", views.dashboard, name="dashboard"),
    path("account/password/", views.AccountPasswordChangeView.as_view(), name="change-password"),
    path("settings/", views.business_settings, name="business-settings"),
    path("manual/", login_required(TemplateView.as_view(template_name="manual.html", extra_context={"title": "User manual"})), name="user-manual"),
    path("reports/", views.reports, name="reports"),
    path("search/", views.search, name="search"),
    path("login/", auth.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("logout/", auth.LogoutView.as_view(), name="logout"),
    path("sales/<int:pk>/refund/", views.record_refund, name="record-refund"),
    path("inventory/<int:pk>/release/", views.release_laptop, name="release-laptop"),
    path("sales/<int:pk>/return/", views.return_laptop, name="return-laptop"),
    path("inventory/photos/<int:pk>/", views.laptop_photo, name="laptop-photo"),
    path("customers/<int:pk>/photo/", views.photo, name="photo"),
    path("<str:section>/", views.records, name="records"),
    path("<str:section>/new/", views.entry, name="new"),
    path("<str:section>/<int:pk>/edit/", views.entry, {"editing": True}, name="change"),
    path("<str:section>/<int:pk>/delete/", views.remove_record, name="delete"),
    path("<str:section>/<int:pk>/", views.entry, name="edit"),
]

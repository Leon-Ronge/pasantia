from django.urls import include, path
from rest_framework.routers import SimpleRouter

from core.views import DashboardView, HolidayViewSet, SettingsView

app_name = "core"

router = SimpleRouter()
router.register("holidays", HolidayViewSet, basename="holidays")

urlpatterns = [
    path("settings/", SettingsView.as_view(), name="settings"),
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("", include(router.urls)),
]

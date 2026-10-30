from django.urls import path
from rest_framework.routers import DefaultRouter

from work.views import (
    HoursMonthlySummaryView,
    TodayView,
    WeekView,
    WorkPlanViewSet,
    WorkSessionViewSet,
)

app_name = "work"

router = DefaultRouter()
router.register("work-sessions", WorkSessionViewSet, basename="work-sessions")
router.register("work-plans", WorkPlanViewSet, basename="work-plans")

urlpatterns = [
    path("today/", TodayView.as_view(), name="today"),
    path("week/", WeekView.as_view(), name="week"),
    path(
        "hours/monthly-summary/",
        HoursMonthlySummaryView.as_view(),
        name="hours-monthly-summary",
    ),
] + router.urls

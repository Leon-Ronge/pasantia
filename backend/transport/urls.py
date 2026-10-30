from rest_framework.routers import DefaultRouter

from transport.views import TravelViewSet

app_name = "transport"

router = DefaultRouter()
router.register("travels", TravelViewSet, basename="travels")

urlpatterns = router.urls

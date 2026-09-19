from rest_framework.routers import SimpleRouter

from .views import ListingViewSet

app_name = 'listings'

router = SimpleRouter()
router.register('listings', ListingViewSet, basename='listing')

urlpatterns = router.urls

from django.urls import path
from rest_framework.routers import SimpleRouter

from .views import CrawlJobViewSet, CrawlOptionsView

app_name = 'crawling'

router = SimpleRouter()
router.register('crawl-jobs', CrawlJobViewSet, basename='crawl-job')

urlpatterns = [
    path('crawl-options/', CrawlOptionsView.as_view(), name='crawl-options'),
    *router.urls,
]

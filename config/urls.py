from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('auth/', include('core.accounts.urls')),
    path('api/locations/', include('core.locations.urls')),
    path('api/', include('core.listings.urls')),
    path('api/', include('core.crawling.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    from drf_spectacular.views import (
        SpectacularAPIView,
        SpectacularRedocView,
        SpectacularSwaggerView,
    )

    urlpatterns += [
        path('__debug__/', include(debug_toolbar.urls)),
        path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
        path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
        path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    ]
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path
from django.conf import settings
from invoices.auth_views import auth_logout, auth_register, auth_session


def health_check(request):
    return JsonResponse({"status": "ok"})


def frontend_app(request):
    index_file = settings.FRONTEND_DIST_DIR / "index.html"
    if not index_file.is_file():
        raise Http404("Frontend build is not installed.")
    return FileResponse(index_file.open("rb"), content_type="text/html")


urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", health_check, name="health-check"),
    path("api/auth/session/", auth_session, name="auth-session"),
    path("api/auth/register/", auth_register, name="auth-register"),
    path("api/auth/logout/", auth_logout, name="auth-logout"),
    path("api/invoices/", include("invoices.urls")),
    path("", frontend_app, name="frontend"),
    re_path(
        r"^(?!api/|admin/|healthz/|static/|media/).*$",
        frontend_app,
        name="frontend-fallback",
    ),
]

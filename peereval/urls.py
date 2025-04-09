"""
URL configuration for peereval project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
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
from django.urls import path, include
from src.views import CustomLogoutView
from django.conf.urls import handler400, handler403, handler404, handler500

urlpatterns = [
    path('admin/', admin.site.urls),
    path("accounts/logout/", CustomLogoutView.as_view(), name="logout"),
    path("accounts/", include("django.contrib.auth.urls")),
    path('', include('src.urls')),
]

# Error handlers
handler400 = 'src.views.bad_request'
handler403 = 'src.views.permission_denied'
handler404 = 'src.views.page_not_found'
handler500 = 'src.views.server_error'

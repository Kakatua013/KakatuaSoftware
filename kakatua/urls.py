"""
URL configuration for kakatua project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from kakatuasoft import views

urlpatterns = [
    # 'name=' é para nomear a pagina que sera chamada e os valores delas estão escritos no final de settings.py
    path('admin/', admin.site.urls),
    path("api-auth/", include("rest_framework.urls")),
    path('page1/', views.fazer_login, name='page1'),
    path('page2/', views.page2, name='page2'),
    path('cadastro/', views.cadastro, name='cadastro'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.fazer_login),
]

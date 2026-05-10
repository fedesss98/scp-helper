from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from bookings.views import ThrottledLoginView

urlpatterns = [
    path('django-admin/', admin.site.urls),
    path('login/', ThrottledLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('', include('bookings.urls')),
]

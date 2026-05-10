from django.urls import path
from . import views

urlpatterns = [
    path('', views.calendar_view, name='home'),
    path('calendar/', views.calendar_view, name='calendar'),
    path('my-bookings/', views.my_bookings, name='my_bookings'),

    # Booking actions
    path('book/', views.book_slot, name='book_slot'),
    path('cancel/<int:booking_id>/', views.cancel_booking, name='cancel_booking'),

    # Admin
    path('admin/users/', views.admin_users, name='admin_users'),
    path('admin/users/create/', views.admin_create_user, name='admin_create_user'),
    path('admin/users/<int:user_id>/password/', views.admin_change_password, name='admin_change_password'),
    path('admin/users/<int:user_id>/delete/', views.admin_delete_user, name='admin_delete_user'),
    path('admin/bookings/', views.admin_all_bookings, name='admin_all_bookings'),
]

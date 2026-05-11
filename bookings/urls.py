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
    path('admin/slots/', views.admin_slots, name='admin_slots'),
    path('admin/slots/create/', views.admin_create_slot, name='admin_create_slot'),
    path('admin/slots/<int:slot_id>/edit/', views.admin_edit_slot, name='admin_edit_slot'),
    path('admin/slots/<int:slot_id>/toggle/', views.admin_toggle_slot, name='admin_toggle_slot'),
    path('admin/slots/<int:slot_id>/delete/', views.admin_delete_slot, name='admin_delete_slot'),
    path('admin/bookings/', views.admin_all_bookings, name='admin_all_bookings'),
    path('admin/bookings/create/', views.admin_create_booking, name='admin_create_booking'),
    path('admin/bookings/<int:booking_id>/edit/', views.admin_edit_booking, name='admin_edit_booking'),
    path('admin/bookings/<int:booking_id>/delete/', views.admin_delete_booking, name='admin_delete_booking'),
]

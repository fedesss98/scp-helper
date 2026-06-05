from django.urls import path

from . import views

urlpatterns = [
    path("", views.race_calendar, name="race_calendar"),
    path("<int:race_id>/subscribe/", views.subscribe_race, name="race_subscribe"),
    path("<int:race_id>/unsubscribe/", views.unsubscribe_race, name="race_unsubscribe"),
    path("<str:external_id>/", views.race_detail, name="race_detail"),
]


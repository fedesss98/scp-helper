from django.contrib.auth.models import User
from django.db import models


class Race(models.Model):
    external_id = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=255, blank=True)
    location = models.CharField(max_length=255, blank=True)
    date = models.DateField(null=True, blank=True)
    category = models.CharField(max_length=100, blank=True)
    url = models.URLField(blank=True)
    program_payload = models.JSONField(default=dict, blank=True)
    last_scraped = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'name', 'external_id']

    def __str__(self):
        label = self.name or self.external_id
        if self.date:
            return f'{label} ({self.date:%Y-%m-%d})'
        return label


class RaceResult(models.Model):
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name='results')
    external_id = models.CharField(max_length=120, unique=True)
    source = models.CharField(max_length=255, blank=True)
    race_number = models.PositiveIntegerField(null=True, blank=True)
    race_date_day = models.CharField(max_length=20, blank=True)
    event = models.CharField(max_length=255, blank=True)
    phase = models.CharField(max_length=120, blank=True)
    position = models.PositiveIntegerField(null=True, blank=True)
    master_class = models.CharField(max_length=20, blank=True)
    finish_time = models.CharField(max_length=40, blank=True)
    lane = models.PositiveIntegerField(null=True, blank=True)
    bib = models.PositiveIntegerField(null=True, blank=True)
    club = models.CharField(max_length=255, blank=True)
    athletes = models.JSONField(default=list, blank=True)
    gap = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=120, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['race', 'race_number', 'position', 'club']

    def __str__(self):
        race_number = self.race_number if self.race_number is not None else '?'
        position = self.position if self.position is not None else '?'
        return f'{self.race.external_id} GARA {race_number} #{position} {self.club}'


class RaceSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='race_subscriptions')
    race = models.ForeignKey(Race, on_delete=models.CASCADE, related_name='subscriptions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'race')
        ordering = ['race__date', 'race__name', 'user__username']

    def __str__(self):
        return f'{self.user.username} -> {self.race}'


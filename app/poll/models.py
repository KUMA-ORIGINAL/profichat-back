from django.db import models


class Voter(models.Model):
    """Участник опроса. Без регистрации: идентифицируется токеном из браузера."""
    token = models.UUIDField(unique=True)
    name = models.CharField(max_length=60)
    wish = models.CharField(max_length=300, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Place(models.Model):
    """Предложенное место для корпоратива."""
    title = models.CharField(max_length=80)
    note = models.CharField(max_length=300, blank=True, default='')
    author = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name='places')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return self.title


class Vote(models.Model):
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE, related_name='votes')
    place = models.ForeignKey(Place, on_delete=models.CASCADE, related_name='votes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['voter', 'place'], name='unique_poll_vote'),
        ]

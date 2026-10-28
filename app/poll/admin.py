from django.contrib import admin

from .models import Place, Vote, Voter

admin.site.register(Voter)
admin.site.register(Place)
admin.site.register(Vote)

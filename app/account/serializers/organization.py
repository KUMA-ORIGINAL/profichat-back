from rest_framework import serializers

from ..models import Organization


class OrganizationShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name")

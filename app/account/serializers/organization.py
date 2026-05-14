from rest_framework import serializers

from ..models import (
    Organization,
    OrganizationAddress,
    OrganizationWorkSchedule,
    OrganizationSocialLink,
    OrganizationService,
    OrganizationGalleryImage,
    SocialNetwork,
)


class OrganizationShortSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name", "logo", "description", "rating")


class OrganizationAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationAddress
        fields = ("id", "address", "is_primary")


class OrganizationWorkScheduleSerializer(serializers.ModelSerializer):
    day_of_week_display = serializers.CharField(source='get_day_of_week_display', read_only=True)

    class Meta:
        model = OrganizationWorkSchedule
        fields = (
            "id", "day_of_week", "day_of_week_display",
            "from_time", "to_time", "is_day_off", "is_round_the_clock",
        )


class SocialNetworkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialNetwork
        fields = ("id", "name", "logo")


class OrganizationSocialLinkSerializer(serializers.ModelSerializer):
    social_network = SocialNetworkSerializer(read_only=True)

    class Meta:
        model = OrganizationSocialLink
        fields = ("id", "social_network", "url")


class OrganizationServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationService
        fields = ("id", "name")


class OrganizationGalleryImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrganizationGalleryImage
        fields = ("id", "image", "order")


class OrganizationMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    middle_name = serializers.CharField(allow_null=True)
    photo = serializers.ImageField(allow_null=True)
    profession = serializers.SerializerMethodField()

    def get_profession(self, obj):
        if obj.profession:
            return {"id": obj.profession.id, "name": obj.profession.name}
        return None


class OrganizationDetailSerializer(serializers.ModelSerializer):
    addresses = OrganizationAddressSerializer(many=True, read_only=True)
    work_schedules = OrganizationWorkScheduleSerializer(many=True, read_only=True)
    social_links = OrganizationSocialLinkSerializer(many=True, read_only=True)
    services = OrganizationServiceSerializer(many=True, read_only=True)
    gallery_images = OrganizationGalleryImageSerializer(many=True, read_only=True)

    class Meta:
        model = Organization
        fields = (
            "id",
            "name",
            "logo",
            "category",
            "description",
            "rating",
            "reviews_count",
            "addresses",
            "work_schedules",
            "social_links",
            "services",
            "gallery_images",
        )

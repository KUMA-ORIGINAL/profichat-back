import django_filters
from django.contrib.auth import get_user_model

User = get_user_model()


class SpecialistFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name='tariffs__price', lookup_expr='gte')
    max_price = django_filters.NumberFilter(field_name='tariffs__price', lookup_expr='lte')

    class Meta:
        model = User
        fields = ['profession', 'min_price', 'max_price']

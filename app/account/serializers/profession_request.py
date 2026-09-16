from rest_framework import serializers

from ..models import ProfessionRequest


class ProfessionRequestSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=ProfessionRequest.NAME_MAX_LENGTH,
        trim_whitespace=True,
        error_messages={
            'blank': 'Укажите название профессии.',
            'required': 'Укажите название профессии.',
            'max_length': f'Название профессии — не длиннее {ProfessionRequest.NAME_MAX_LENGTH} символов.',
        },
    )
    description = serializers.CharField(
        max_length=ProfessionRequest.DESCRIPTION_MAX_LENGTH,
        trim_whitespace=True,
        error_messages={
            'blank': 'Добавьте краткое описание профессии.',
            'required': 'Добавьте краткое описание профессии.',
            'max_length': f'Описание — не длиннее {ProfessionRequest.DESCRIPTION_MAX_LENGTH} символов.',
        },
    )

    class Meta:
        model = ProfessionRequest
        fields = (
            'id',
            'name',
            'description',
            'status',
            'reason',
            'source',
            'created_at',
            'profession_category',
        )
        read_only_fields = ('id', 'status', 'reason', 'source', 'created_at', 'profession_category')

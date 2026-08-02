from rest_framework import serializers


class MamaDocClientIdQuerySerializer(serializers.Serializer):
    client_id = serializers.IntegerField()


class MamaDocConclusionQuerySerializer(serializers.Serializer):
    client_id = serializers.IntegerField()
    conclusion_id = serializers.IntegerField()


class MamaDocServiceLineSerializer(serializers.Serializer):
    """Читает сырой dict NewCRM `ServiceLinePayload` (camelCase-ключи)."""
    service_name = serializers.CharField(source="service.name", default=None)
    employee_full_name = serializers.CharField(source="employee.fullName", default=None)
    duration_minutes = serializers.IntegerField(source="durationMinutes", default=None)
    conclusion_state = serializers.CharField(source="conclusionState", default=None)
    conclusion_id = serializers.IntegerField(source="conclusionId", default=None)


class MamaDocVisitSerializer(serializers.Serializer):
    """Читает сырой dict NewCRM `AppointmentPayload` (camelCase-ключи)."""
    starts_at = serializers.DateTimeField(source="startsAt")
    service_lines = MamaDocServiceLineSerializer(source="serviceLines", many=True, default=list)


class MamaDocDiagnosisSerializer(serializers.Serializer):
    code = serializers.CharField(source="diagnosisCode", default=None)
    title = serializers.CharField(default=None)
    display_name = serializers.CharField(source="displayName", default=None)


class MamaDocConclusionDetailSerializer(serializers.Serializer):
    """
    Читает сырой dict NewCRM `ConclusionPayload` (camelCase-ключи).

    Поля объекта `doctor` за пределами `fullName` (например, специальность)
    не подтверждены по реальному контракту NewCRM — уточнить перед подключением.
    """
    doctor_full_name = serializers.CharField(source="doctor.fullName", default=None)
    complaints = serializers.CharField(default="", allow_blank=True)
    anamnesis = serializers.CharField(default="", allow_blank=True)
    objective = serializers.CharField(default="", allow_blank=True)
    conclusion = serializers.CharField(default="", allow_blank=True)
    diagnosis_data = MamaDocDiagnosisSerializer(source="diagnosisData", many=True, default=list)
    weight_kg = serializers.CharField(source="weightKg", default=None)
    height_cm = serializers.CharField(source="heightCm", default=None)
    temperature = serializers.CharField(default=None)
    photo_urls = serializers.ListField(source="photoUrls", child=serializers.CharField(), default=list)
    created_at = serializers.DateTimeField(source="createdAt")

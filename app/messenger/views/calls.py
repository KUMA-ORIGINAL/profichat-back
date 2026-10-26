from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from messenger.models import Call
from messenger.serializers import CallSerializer
from messenger.services import access, calls


class StartCallRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Call.Kind.choices, default=Call.Kind.AUDIO)


CallSessionSerializer = inline_serializer(
    name="CallSession",
    fields={
        "call": CallSerializer(),
        "livekit_url": serializers.CharField(),
        "token": serializers.CharField(allow_null=True),
    },
)


def _session(call, token) -> dict:
    """Ответ start/accept: звонок, адрес LiveKit для клиента и токен комнаты (null для busy)."""
    return {"call": CallSerializer(call).data, "livekit_url": settings.LIVEKIT_URL, "token": token}


@extend_schema(tags=["Messenger"])
class ChatCallsView(APIView):
    """Начать звонок собеседнику по чату."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Start call",
        request=StartCallRequestSerializer,
        responses={201: CallSessionSerializer},
    )
    def post(self, request, channel_id):
        chat = access.ensure_member(request.user, channel_id)
        serializer = StartCallRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        call, token = calls.start_call(chat, request.user, serializer.validated_data["kind"])
        return Response(_session(call, token), status=status.HTTP_201_CREATED)


@extend_schema(tags=["Messenger"])
class CallDetailView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Get call", responses=CallSerializer)
    def get(self, request, pk):
        return Response(CallSerializer(calls.get_call_for_user(pk, request.user)).data)


@extend_schema(tags=["Messenger"])
class AcceptCallView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(summary="Accept call", request=None, responses=CallSessionSerializer)
    def post(self, request, pk):
        call = calls.get_call_for_user(pk, request.user)
        token = calls.accept_call(call, request.user)
        call.refresh_from_db()
        return Response(_session(call, token))


class _CallTransitionView(APIView):
    permission_classes = [IsAuthenticated]
    transition = None

    def post(self, request, pk):
        call = calls.get_call_for_user(pk, request.user)
        call = self.transition(call, request.user)
        return Response(CallSerializer(call).data)


@extend_schema(tags=["Messenger"])
class DeclineCallView(_CallTransitionView):
    transition = staticmethod(calls.decline_call)

    @extend_schema(summary="Decline call", request=None, responses=CallSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


@extend_schema(tags=["Messenger"])
class CancelCallView(_CallTransitionView):
    transition = staticmethod(calls.cancel_call)

    @extend_schema(summary="Cancel call", request=None, responses=CallSerializer)
    def post(self, request, pk):
        return super().post(request, pk)


@extend_schema(tags=["Messenger"])
class EndCallView(_CallTransitionView):
    transition = staticmethod(calls.end_call)

    @extend_schema(summary="End call", request=None, responses=CallSerializer)
    def post(self, request, pk):
        return super().post(request, pk)

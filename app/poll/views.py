from django.db import transaction
from django.db.models import Q
from django.shortcuts import render
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .models import Place, Vote, Voter


def page(request):
    return render(request, 'poll/corporate.html')


class PollView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'corporate_poll'


class VoterSerializer(serializers.Serializer):
    token = serializers.UUIDField()
    name = serializers.CharField(max_length=60)

    def get_voter(self):
        voter, _ = Voter.objects.get_or_create(
            token=self.validated_data['token'],
            defaults={'name': self.validated_data['name']},
        )
        if voter.name != self.validated_data['name']:
            voter.name = self.validated_data['name']
            voter.save(update_fields=['name'])
        return voter


class StateView(PollView):
    def get(self, request):
        places = Place.objects.select_related('author').prefetch_related('votes__voter')
        return Response({
            'places': [{
                'id': p.id,
                'title': p.title,
                'note': p.note,
                'author': p.author.token,
                'authorName': p.author.name,
                'voters': [v.voter.token for v in p.votes.all()],
            } for p in places],
            'people': [{
                'token': v.token,
                'name': v.name,
                'wish': v.wish,
            } for v in Voter.objects.filter(Q(votes__isnull=False) | ~Q(wish='')).distinct()],
        })


class PlaceSerializer(VoterSerializer):
    title = serializers.CharField(max_length=80)
    note = serializers.CharField(max_length=300, allow_blank=True, required=False, default='')


class PlaceCreateView(PollView):
    def post(self, request):
        s = PlaceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        with transaction.atomic():
            voter = s.get_voter()
            place = Place.objects.create(
                title=s.validated_data['title'].strip(),
                note=s.validated_data['note'].strip(),
                author=voter,
            )
            Vote.objects.create(voter=voter, place=place)
        return Response({'id': place.id}, status=status.HTTP_201_CREATED)


class PlaceDeleteView(PollView):
    def delete(self, request, pk):
        token = serializers.UUIDField().run_validation(request.query_params.get('token'))
        deleted, _ = Place.objects.filter(pk=pk, author__token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT if deleted else status.HTTP_404_NOT_FOUND)


class VoteSerializer(VoterSerializer):
    place_id = serializers.IntegerField()
    on = serializers.BooleanField()


class VoteView(PollView):
    def post(self, request):
        s = VoteSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        place = Place.objects.filter(pk=s.validated_data['place_id']).first()
        if place is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        voter = s.get_voter()
        if s.validated_data['on']:
            Vote.objects.get_or_create(voter=voter, place=place)
        else:
            Vote.objects.filter(voter=voter, place=place).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WishSerializer(VoterSerializer):
    wish = serializers.CharField(max_length=300, allow_blank=True)


class WishView(PollView):
    def post(self, request):
        s = WishSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        voter = s.get_voter()
        voter.wish = s.validated_data['wish'].strip()
        voter.save(update_fields=['wish'])
        return Response(status=status.HTTP_204_NO_CONTENT)

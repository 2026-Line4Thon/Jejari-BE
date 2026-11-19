# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework import status

from .models import Place
from .serializers import PlaceSerializer


class PlaceListView(APIView):
    permission_classes = [AllowAny]  # 비로그인/등록 전 단계에서도 조회 가능하도록 허용

    def get(self, request):
        places = Place.objects.all()  # Meta의 ordering = ['name'] 적용됨
        serializer = PlaceSerializer(places, many=True)
        return Response(
            {"places": serializer.data},
            status=status.HTTP_200_OK
        )
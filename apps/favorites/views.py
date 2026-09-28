from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.properties.models import Property

from .models import Favorite
from .serializers import FavoriteCreateSerializer, FavoriteSerializer


class FavoriteListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FavoriteSerializer

    def get_queryset(self):
        return (
            Favorite.objects.filter(user=self.request.user)
            .select_related("property__city", "property__country")
            .prefetch_related("property__images", "property__amenities")
            .order_by("-created_at")
        )


class FavoriteAddView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FavoriteCreateSerializer

    def post(self, request):
        serializer = FavoriteCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prop = Property.objects.filter(
            pk=serializer.validated_data["property_id"],
            status=Property.Status.PUBLISHED,
        ).first()
        if prop is None:
            from apps.common.exceptions import NotFoundError

            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        favorite, _ = Favorite.objects.get_or_create(user=request.user, property=prop)
        return Response(FavoriteSerializer(favorite).data,
                        status=status.HTTP_201_CREATED)


class FavoriteRemoveView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, property_id):
        Favorite.objects.filter(user=request.user, property_id=property_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FavoriteCheckView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, property_id):
        exists = Favorite.objects.filter(
            user=request.user, property_id=property_id
        ).exists()
        return Response({"is_favorite": exists})

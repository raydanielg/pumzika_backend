"""Promotion endpoints — guests validate; staff manage."""
from __future__ import annotations

from rest_framework import generics, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import PROMOTION_MANAGE
from apps.common.exceptions import NotFoundError
from apps.common.permissions import PermissionRequired
from apps.properties.models import Property

from . import services
from .models import Promotion
from .serializers import PromotionSerializer, ValidatePromoSerializer


class PromotionViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PROMOTION_MANAGE,)
    serializer_class = PromotionSerializer
    queryset = Promotion.objects.all().order_by("-created_at")


class ValidatePromoView(APIView):
    """Check a code before booking — returns the discount the engine computed."""

    permission_classes = [IsAuthenticated]
    serializer_class = ValidatePromoSerializer

    def post(self, request):
        serializer = ValidatePromoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        prop = Property.objects.filter(pk=data["property_id"]).first()
        if prop is None:
            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        promo, discount = services.validate_for_booking(
            data["code"], prop, request.user, data["check_in"], data["check_out"]
        )
        return Response({
            "code": promo.code,
            "discount": str(discount),
            "currency": prop.currency,
        })


class PromotionListPublicView(generics.ListAPIView):
    """Active public promotions (marketing surface)."""

    permission_classes = [IsAuthenticated]
    serializer_class = PromotionSerializer
    pagination_class = None

    def get_queryset(self):
        from django.utils import timezone

        now = timezone.now()
        return Promotion.objects.filter(
            is_active=True, valid_from__lte=now, valid_until__gte=now
        )

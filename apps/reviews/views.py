"""Review endpoints."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import REVIEW_MODERATE
from apps.common.exceptions import NotFoundError
from apps.common.permissions import PermissionRequired
from apps.admin_panel.services import audit

from . import services
from .models import GuestReview, HostReview, PropertyReview
from .serializers import (
    GuestReviewCreateSerializer,
    GuestReviewSerializer,
    HostReviewSerializer,
    PropertyReviewSerializer,
    ReviewCreateSerializer,
)


class PropertyReviewListView(generics.ListAPIView):
    """Public reviews for a property (published only)."""

    permission_classes = [AllowAny]
    serializer_class = PropertyReviewSerializer

    def get_queryset(self):
        return (
            PropertyReview.objects.filter(
                property_id=self.kwargs["property_id"], is_published=True
            )
            .select_related("reviewer")
            .order_by("-created_at")
        )


class CreatePropertyReviewView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReviewCreateSerializer

    def post(self, request):
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sub = {k: data[k] for k in ("cleanliness", "communication", "location",
                                    "value", "accuracy") if k in data}
        review = services.create_property_review(
            request.user, data["booking_id"], data["rating"],
            data.get("comment", ""), **sub,
        )
        audit(actor=request.user, action="review.created", target=review,
              request=request)
        return Response(PropertyReviewSerializer(review).data,
                        status=status.HTTP_201_CREATED)


class CreateHostReviewView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReviewCreateSerializer

    def post(self, request):
        serializer = ReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sub = {k: data[k] for k in ("communication",) if k in data}
        review = services.create_host_review(
            request.user, data["booking_id"], data["rating"],
            data.get("comment", ""), **sub,
        )
        return Response(HostReviewSerializer(review).data,
                        status=status.HTTP_201_CREATED)


class CreateGuestReviewView(APIView):
    """Host reviews their guest."""

    permission_classes = [IsAuthenticated]
    serializer_class = GuestReviewCreateSerializer

    def post(self, request):
        serializer = GuestReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sub = {k: data[k] for k in ("cleanliness", "communication",
                                    "house_rules_respect") if k in data}
        review = services.create_guest_review(
            request.user, data["booking_id"], data["rating"],
            data.get("comment", ""), **sub,
        )
        return Response(GuestReviewSerializer(review).data,
                        status=status.HTTP_201_CREATED)


class HostReviewsView(generics.ListAPIView):
    """Public reviews for a host."""

    permission_classes = [AllowAny]
    serializer_class = HostReviewSerializer

    def get_queryset(self):
        return HostReview.objects.filter(
            host_id=self.kwargs["host_id"], is_published=True
        ).select_related("reviewer").order_by("-created_at")


class ModerateReviewView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (REVIEW_MODERATE,)

    def post(self, request, review_type, pk):
        model_map = {
            "property": PropertyReview,
            "host": HostReview,
            "guest": GuestReview,
        }
        model = model_map.get(review_type)
        if model is None:
            raise NotFoundError("Unknown review type.", code="NOT_FOUND")
        review = model.objects.filter(pk=pk).first()
        if review is None:
            raise NotFoundError("Review not found.", code="REVIEW_NOT_FOUND")
        publish = bool(request.data.get("publish", True))
        services.moderate_review(review, publish, request.user)
        audit(actor=request.user,
              action=f"review.{'published' if publish else 'hidden'}",
              target=review, request=request)
        return Response({"id": str(review.id), "is_published": review.is_published})

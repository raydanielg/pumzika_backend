"""Booking endpoints."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import decorators, generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.exceptions import PermissionDeniedError
from apps.admin_panel.services import audit
from apps.properties.models import Property
from apps.common.exceptions import NotFoundError

from . import services
from .models import Booking, CancellationPolicy
from .serializers import (
    BookingCreateSerializer,
    BookingQuoteSerializer,
    BookingSerializer,
    CancelBookingSerializer,
    CancellationPolicySerializer,
    HostBookingSerializer,
)


class CancellationPolicyListView(generics.ListAPIView):
    """Public — guests need to see cancellation terms before booking."""

    serializer_class = CancellationPolicySerializer
    queryset = CancellationPolicy.objects.filter(is_active=True).prefetch_related("rules")
    pagination_class = None
    permission_classes = [IsAuthenticated]


class BookingViewSet(viewsets.GenericViewSet,
                     generics.ListAPIView,
                     generics.RetrieveAPIView,
                     generics.CreateAPIView):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "property"]

    def get_queryset(self):
        qs = Booking.objects.select_related(
            "property", "property__city", "property__host", "guest", "price"
        ).prefetch_related("guests", "status_history")
        user = self.request.user
        if self.request.query_params.get("as") == "host" or user.is_staff_role:
            if user.is_staff_role:
                return qs  # staff see everything via admin endpoints
            return qs.filter(property__host=user)
        return qs.filter(guest=user)

    def get_object(self):
        return services.get_booking_for_user(self.kwargs["pk"], self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return BookingCreateSerializer
        user = getattr(self.request, "user", None)
        obj = getattr(self, "_obj", None)
        if getattr(user, "is_staff_role", False) or (
            obj and obj.property.host_id == getattr(user, "id", None)
        ):
            return HostBookingSerializer
        return BookingSerializer

    def retrieve(self, request, *args, **kwargs):
        obj = self.get_object()
        self._obj = obj
        return Response(self.get_serializer(obj).data)

    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        serializer = BookingCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        booking = services.create_booking(
            request.user,
            idempotency_key=request.headers.get("Idempotency-Key"),
            property_id=data["property_id"],
            check_in=data["check_in"],
            check_out=data["check_out"],
            guests_count=data["guests_count"],
            promo_code=data.get("promo_code", ""),
            special_requests=data.get("special_requests", ""),
            guest_details=data.get("guests"),
            request=request,
        )
        return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)

    @decorators.action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        serializer = CancelBookingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = services.cancel_booking(
            booking, request.user, serializer.validated_data.get("reason", "")
        )
        audit(actor=request.user, action="booking.cancelled",
              target=booking, request=request)
        return Response(BookingSerializer(booking).data)

    @decorators.action(detail=True, methods=["post"])
    def check_in(self, request, pk=None):
        booking = self.get_object()
        if booking.property.host_id != request.user.id and not request.user.is_staff_role:
            raise PermissionDeniedError("Only the host can check in a guest.")
        booking = services.check_in(booking, request.user)
        audit(actor=request.user, action="booking.checked_in",
              target=booking, request=request)
        return Response(BookingSerializer(booking).data)

    @decorators.action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        booking = self.get_object()
        if booking.property.host_id != request.user.id and not request.user.is_staff_role:
            raise PermissionDeniedError("Only the host can complete a booking.")
        booking = services.complete_booking(booking, request.user)
        audit(actor=request.user, action="booking.completed",
              target=booking, request=request)
        return Response(BookingSerializer(booking).data)


class BookingQuoteView(APIView):
    """Price preview — computed on the backend, never trusted from the client."""

    permission_classes = [IsAuthenticated]
    serializer_class = BookingQuoteSerializer

    def post(self, request):
        serializer = BookingQuoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        prop = Property.objects.filter(pk=data["property_id"]).first()
        if prop is None:
            raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")
        quote = services.quote_for_property(
            prop, data["check_in"], data["check_out"],
            data.get("promo_code", ""), guest=request.user,
        )
        return Response(quote)

"""Booking endpoints."""
from __future__ import annotations

from django.db import models as db_models
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import decorators, generics, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.schema import schema_empty_queryset
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
        if getattr(self, "swagger_fake_view", False):
            return schema_empty_queryset(self)
        qs = Booking.objects.select_related(
            "property", "property__city", "property__host", "guest", "price"
        ).prefetch_related("guests", "status_history")
        params = self.request.query_params
        user = self.request.user
        if params.get("as") == "host" or user.is_staff_role:
            if user.is_staff_role:
                pass  # staff see everything
            else:
                qs = qs.filter(property__host=user)
        else:
            qs = qs.filter(guest=user)

        # Convenience buckets — common client-side filters.
        bucket = params.get("bucket")
        today = timezone.now().date()
        if bucket == "upcoming":
            qs = qs.filter(status=Booking.Status.CONFIRMED, check_in__gte=today)
        elif bucket == "in_progress":
            qs = qs.filter(status=Booking.Status.CHECKED_IN)
        elif bucket == "completed":
            qs = qs.filter(status=Booking.Status.COMPLETED)
        elif bucket == "cancelled":
            qs = qs.filter(status=Booking.Status.CANCELLED)
        elif bucket == "unpaid":
            qs = qs.filter(status__in=[Booking.Status.PENDING,
                                       Booking.Status.AWAITING_PAYMENT])

        # Reference + date + counterparty search.
        if ref := params.get("reference"):
            qs = qs.filter(reference__icontains=ref)
        if params.get("check_in_from"):
            qs = qs.filter(check_in__gte=params["check_in_from"])
        if params.get("check_in_to"):
            qs = qs.filter(check_in__lte=params["check_in_to"])
        if params.get("check_out_from"):
            qs = qs.filter(check_out__gte=params["check_out_from"])
        if q := params.get("q"):
            # Staff/hosts search guests; guests search property title.
            qs = qs.filter(
                db_models.Q(guest__email__icontains=q)
                | db_models.Q(guest__first_name__icontains=q)
                | db_models.Q(guest__last_name__icontains=q)
                | db_models.Q(property_title__icontains=q)
                | db_models.Q(reference__icontains=q)
            )
        return qs.order_by("-created_at")

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
        guests = data.get("guests") or {}
        booking = services.create_booking(
            request.user,
            idempotency_key=request.headers.get("Idempotency-Key"),
            property_id=data["property_id"],
            check_in=data["check_in"],
            check_out=data["check_out"],
            guests_count=data.get("guests_count") or 1,
            unit_id=data.get("unit_id"),
            adults=guests.get("adults"),
            children=guests.get("children", 0),
            infants=guests.get("infants", 0),
            promo_code=data.get("promo_code", ""),
            special_requests=data.get("special_requests", ""),
            guest_details=data.get("guest_details"),
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
    def no_show(self, request, pk=None):
        booking = self.get_object()
        if booking.property.host_id != request.user.id and not request.user.is_staff_role:
            raise PermissionDeniedError("Only the host can mark a no-show.")
        booking = services.mark_no_show(booking, request.user)
        audit(actor=request.user, action="booking.no_show",
              target=booking, request=request)
        return Response(BookingSerializer(booking).data)

    @decorators.action(detail=True, methods=["get", "post"])
    def notes(self, request, pk=None):
        """Booking notes — internal notes never reach guests."""
        from .models import BookingNote
        from .serializers import BookingNoteSerializer

        booking = self.get_object()
        is_privileged = (
            request.user.is_staff_role
            or booking.property.host_id == request.user.id
        )
        if request.method == "POST":
            serializer = BookingNoteSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            BookingNote.objects.create(
                booking=booking, author=request.user,
                body=serializer.validated_data["body"],
                is_internal=(
                    is_privileged
                    and serializer.validated_data.get("is_internal", False)
                ),
            )
            return Response({"detail": "Note added."}, status=201)
        qs = booking.notes.all()
        if not is_privileged:
            qs = qs.filter(is_internal=False)
        return Response(BookingNoteSerializer(qs, many=True).data)

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
        unit = None
        if data.get("unit_id"):
            unit = prop.units.filter(pk=data["unit_id"], is_active=True).first()
            if unit is None:
                raise NotFoundError("Unit not found.", code="UNIT_NOT_FOUND")
        quote = services.quote_for_property(
            prop, data["check_in"], data["check_out"],
            data.get("promo_code", ""), guest=request.user, unit=unit,
        )
        return Response(quote)

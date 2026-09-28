"""Payment endpoints + provider webhooks."""
from __future__ import annotations

import json

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import PAYMENT_REFUND, PAYMENT_VIEW_ALL
from apps.common.permissions import PermissionRequired
from apps.common.throttles import PaymentRateThrottle, WebhookRateThrottle
from apps.admin_panel.services import audit

from . import services
from .models import Payment, PaymentProvider, Refund
from .serializers import (
    PaymentInitiateSerializer,
    PaymentProviderSerializer,
    PaymentSerializer,
    RefundCreateSerializer,
    RefundSerializer,
)


class ProviderListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentProviderSerializer
    pagination_class = None

    def get_queryset(self):
        return services.active_providers()


class InitiatePaymentView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [PaymentRateThrottle]
    serializer_class = PaymentInitiateSerializer

    def post(self, request):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.initiate_payment(
            request.user,
            booking_id=serializer.validated_data["booking_id"],
            provider_code=serializer.validated_data["provider"],
            idempotency_key=serializer.validated_data["idempotency_key"]
            or request.headers.get("Idempotency-Key"),
            method_details=serializer.validated_data.get("method_details"),
        )
        audit(actor=request.user, action="payment.initiated",
              target=payment, request=request)
        return Response(PaymentSerializer(payment).data,
                        status=status.HTTP_201_CREATED)


class MyPaymentsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "currency"]

    def get_queryset(self):
        return Payment.objects.filter(
            booking__guest=self.request.user
        ).select_related("provider", "booking").order_by("-created_at")


class PaymentDetailView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer

    def get_queryset(self):
        user = self.request.user
        qs = Payment.objects.select_related("provider", "booking__property")
        if user.is_staff_role:
            return qs
        return qs.filter(booking__guest=user)


class PaymentReceiptView(APIView):
    """Structured receipt for a successful payment — guest or staff only."""

    permission_classes = [IsAuthenticated]
    serializer_class = PaymentSerializer

    def get(self, request, pk):
        payment = Payment.objects.select_related(
            "provider", "booking__guest", "booking__property"
        ).filter(pk=pk).first()
        if payment is None:
            from apps.common.exceptions import NotFoundError

            raise NotFoundError("Payment not found.", code="PAYMENT_NOT_FOUND")
        if not (
            payment.booking.guest_id == request.user.id
            or request.user.is_staff_role
        ):
            from apps.common.exceptions import PermissionDeniedError

            raise PermissionDeniedError("You cannot view this receipt.")
        if payment.status not in (Payment.Status.SUCCESS,
                                  Payment.Status.PARTIALLY_REFUNDED,
                                  Payment.Status.REFUNDED):
            from apps.common.exceptions import BusinessError

            raise BusinessError("No receipt for an unpaid payment.",
                                code="RECEIPT_UNAVAILABLE")
        booking = payment.booking
        return Response({
            "receipt_reference": f"RCT-{payment.reference}",
            "payment_reference": payment.reference,
            "booking_reference": booking.reference,
            "external_reference": payment.external_reference,
            "provider": payment.provider.code,
            "amount": str(payment.amount),
            "currency": payment.currency,
            "status": payment.status,
            "paid_at": payment.paid_at,
            "property": {"id": str(booking.property_id),
                         "title": booking.property.title},
            "guest": {"id": str(booking.guest_id),
                      "name": booking.guest.full_name,
                      "email": booking.guest.email},
            "issued_at": payment.updated_at,
        })


@method_decorator(csrf_exempt, name="dispatch")
class ProviderWebhookView(APIView):
    """POST /api/v1/payments/webhooks/<provider>/

    Provider calls this — signature-verified, deduplicated, retry-safe.
    Auth is the provider signature, not a user session, hence AllowAny + CSRF
    exempt.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [WebhookRateThrottle]
    serializer_class = PaymentSerializer  # docs hint only

    def post(self, request, provider: str):
        headers = {k.lower().replace("http_", "").replace("_", "-"): v
                   for k, v in request.META.items() if k.startswith("HTTP_")}
        event = services.process_webhook(provider.upper(), request.body, headers)
        return Response({"status": event.status})


class AdminRefundView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PAYMENT_REFUND,)
    serializer_class = RefundCreateSerializer

    def post(self, request):
        serializer = RefundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = Payment.objects.select_related("booking").filter(
            pk=serializer.validated_data["payment_id"]
        ).first()
        if payment is None:
            from apps.common.exceptions import NotFoundError

            raise NotFoundError("Payment not found.", code="PAYMENT_NOT_FOUND")
        refund = services.initiate_refund(
            booking=payment.booking,
            amount=serializer.validated_data["amount"],
            reason=serializer.validated_data.get("reason", "Admin refund"),
            requested_by=request.user,
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        audit(actor=request.user, action="payment.refund",
              target=refund or payment, request=request)
        if refund is None:
            return Response({"detail": "No refundable payment found."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(RefundSerializer(refund).data,
                        status=status.HTTP_201_CREATED)


class AdminRefundListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PAYMENT_VIEW_ALL,)
    serializer_class = RefundSerializer

    def get_queryset(self):
        return Refund.objects.select_related("payment", "booking").order_by("-created_at")

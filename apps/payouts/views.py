"""Wallet + payout endpoints."""
from __future__ import annotations

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import PAYOUT_APPROVE, PAYOUT_REQUEST, PAYOUT_VIEW_ALL
from apps.common.permissions import PermissionRequired
from apps.admin_panel.services import audit

from . import services
from .models import Payout, PayoutMethod, WalletTransaction
from .serializers import (
    PayoutMethodSerializer,
    PayoutProcessSerializer,
    PayoutRequestSerializer,
    PayoutSerializer,
    WalletSerializer,
    WalletTransactionSerializer,
)


class MyWalletView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletSerializer

    def get(self, request):
        return Response(WalletSerializer(services.get_wallet(request.user)).data)


class MyWalletTransactionsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = WalletTransactionSerializer

    def get_queryset(self):
        wallet = services.get_wallet(self.request.user)
        return WalletTransaction.objects.filter(wallet=wallet)


class PayoutMethodViewSet(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PayoutMethodSerializer

    def get_queryset(self):
        return PayoutMethod.objects.filter(user=self.request.user, is_active=True)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PayoutMethodDetailView(generics.RetrieveDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PayoutMethodSerializer

    def get_queryset(self):
        return PayoutMethod.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=["is_active", "updated_at"])


class MyPayoutsView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PayoutSerializer

    def get_queryset(self):
        return Payout.objects.filter(user=self.request.user).select_related("method")


class RequestPayoutView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PAYOUT_REQUEST,)
    serializer_class = PayoutRequestSerializer

    def post(self, request):
        serializer = PayoutRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = services.request_payout(
            request.user,
            serializer.validated_data["method_id"],
            serializer.validated_data["amount"],
            idempotency_key=request.headers.get("Idempotency-Key"),
        )
        audit(actor=request.user, action="payout.requested",
              target=payout, request=request)
        return Response(PayoutSerializer(payout).data,
                        status=status.HTTP_201_CREATED)


class AdminPayoutListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PAYOUT_VIEW_ALL,)
    serializer_class = PayoutSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "currency"]

    def get_queryset(self):
        return Payout.objects.select_related("user", "method").order_by("-requested_at")


class AdminPayoutProcessView(APIView):
    permission_classes = [IsAuthenticated, PermissionRequired]
    required_permissions = (PAYOUT_APPROVE,)
    serializer_class = PayoutProcessSerializer

    def post(self, request, pk):
        serializer = PayoutProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payout = services.process_payout(
            request.user, pk,
            serializer.validated_data["approve"],
            serializer.validated_data.get("reason", ""),
        )
        return Response(PayoutSerializer(payout).data)

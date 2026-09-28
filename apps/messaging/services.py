"""Conversation/message services — participant checks enforced here."""
from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.common.exceptions import NotFoundError, PermissionDeniedError
from apps.properties.models import Property

from .models import Conversation, ConversationParticipant, Message


def get_conversation_for_user(user, conversation_id) -> Conversation:
    conversation = Conversation.objects.filter(pk=conversation_id).first()
    if conversation is None:
        raise NotFoundError("Conversation not found.", code="CONVERSATION_NOT_FOUND")
    if not user.is_staff_role and not conversation.participants.filter(
        user=user
    ).exists():
        raise PermissionDeniedError("You are not a participant in this conversation.")
    return conversation


@transaction.atomic
def start_conversation(user, property_id, body: str, booking_id=None) -> Conversation:
    prop = Property.objects.filter(pk=property_id).first()
    if prop is None:
        raise NotFoundError("Property not found.", code="PROPERTY_NOT_FOUND")

    # Reuse an existing guest-host thread for the same property+booking.
    conversation = (
        Conversation.objects.filter(property=prop, booking_id=booking_id)
        .filter(participants__user=user)
        .filter(participants__user=prop.host)
        .first()
    )
    if conversation is None:
        conversation = Conversation.objects.create(
            property=prop, booking_id=booking_id, subject=prop.title
        )
        ConversationParticipant.objects.bulk_create(
            [
                ConversationParticipant(conversation=conversation, user=user),
                ConversationParticipant(conversation=conversation, user=prop.host),
            ]
        )
    if body:
        send_message(user, conversation.id, body)
    return conversation


@transaction.atomic
def send_message(user, conversation_id, body: str,
                 attachments: list | None = None) -> Message:
    if user.has_restriction("MESSAGING"):
        raise BusinessError("Your account is restricted from messaging.",
                            code="CAPABILITY_RESTRICTED")
    conversation = get_conversation_for_user(user, conversation_id)
    message = conversation.messages.create(sender=user, body=body)
    if attachments:
        message.attachments.bulk_create(
            [message.attachments.model(message=message, file=f) for f in attachments]
        )
    # Sender's own message counts as read.
    ConversationParticipant.objects.filter(
        conversation=conversation, user=user
    ).update(last_read_at=timezone.now())

    from apps.notifications.tasks import notify_new_message

    notify_new_message.delay(str(message.id))
    return message


@transaction.atomic
def mark_read(user, conversation_id) -> None:
    conversation = get_conversation_for_user(user, conversation_id)
    ConversationParticipant.objects.filter(
        conversation=conversation, user=user
    ).update(last_read_at=timezone.now())

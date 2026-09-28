from django.contrib import admin

from .models import Conversation, ConversationParticipant, Message, MessageAttachment


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "property", "booking", "subject", "is_active")
    search_fields = ("subject",)


admin.site.register([ConversationParticipant, Message, MessageAttachment])

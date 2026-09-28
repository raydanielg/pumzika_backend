from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("", views.ConversationListView.as_view(), name="list"),
    path("start/", views.StartConversationView.as_view(), name="start"),
    path("<uuid:pk>/", views.ConversationDetailView.as_view(), name="detail"),
    path("<uuid:pk>/messages/", views.MessageListView.as_view(), name="messages"),
    path("<uuid:pk>/messages/send/", views.SendMessageView.as_view(), name="send"),
    path("<uuid:pk>/read/", views.MarkReadView.as_view(), name="read"),
]

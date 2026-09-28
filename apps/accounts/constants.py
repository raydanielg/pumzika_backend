"""Stable permission codes enforced by the backend.

Codes are granted to roles through the RolePermission table — never rely on
frontend role checks.
"""

USER_VIEW = "users.view"
USER_UPDATE = "users.update"
USER_MANAGE = "users.manage"

PROPERTY_CREATE = "properties.create"
PROPERTY_UPDATE = "properties.update"
PROPERTY_VIEW_ALL = "properties.view_all"
PROPERTY_APPROVE = "properties.approve"
PROPERTY_SUSPEND = "properties.suspend"

BOOKING_VIEW = "bookings.view"
BOOKING_VIEW_ALL = "bookings.view_all"
BOOKING_CANCEL = "bookings.cancel"

PAYMENT_VIEW = "payments.view"
PAYMENT_VIEW_ALL = "payments.view_all"
PAYMENT_REFUND = "payments.refund"

PAYOUT_REQUEST = "payouts.request"
PAYOUT_APPROVE = "payouts.approve"
PAYOUT_VIEW_ALL = "payouts.view_all"

KYC_SUBMIT = "kyc.submit"
KYC_REVIEW = "kyc.review"
KYC_VIEW_ALL = "kyc.view_all"

REVIEW_MODERATE = "reviews.moderate"
DISPUTE_MANAGE = "disputes.manage"

LOCATION_MANAGE = "locations.manage"
AMENITY_MANAGE = "amenities.manage"
SETTINGS_UPDATE = "settings.update"
PROMOTION_MANAGE = "promotions.manage"
TAX_MANAGE = "taxes.manage"
NOTIFICATION_TEMPLATE_MANAGE = "notifications.manage_templates"
AUDIT_VIEW = "audit.view"
ANALYTICS_VIEW = "analytics.view"
SECURITY_VIEW = "security.view"
INCIDENT_MANAGE = "security.incidents"

ALL_CODES = [
    USER_VIEW, USER_UPDATE, USER_MANAGE,
    PROPERTY_CREATE, PROPERTY_UPDATE, PROPERTY_VIEW_ALL,
    PROPERTY_APPROVE, PROPERTY_SUSPEND,
    BOOKING_VIEW, BOOKING_VIEW_ALL, BOOKING_CANCEL,
    PAYMENT_VIEW, PAYMENT_VIEW_ALL, PAYMENT_REFUND,
    PAYOUT_REQUEST, PAYOUT_APPROVE, PAYOUT_VIEW_ALL,
    KYC_SUBMIT, KYC_REVIEW, KYC_VIEW_ALL,
    REVIEW_MODERATE, DISPUTE_MANAGE,
    LOCATION_MANAGE, AMENITY_MANAGE, SETTINGS_UPDATE,
    PROMOTION_MANAGE, TAX_MANAGE, NOTIFICATION_TEMPLATE_MANAGE,
    AUDIT_VIEW, ANALYTICS_VIEW, SECURITY_VIEW, INCIDENT_MANAGE,
]

# Default grants per role — seeded via `seed_permissions`. SUPER_ADMIN
# implicitly holds every code.
ROLE_DEFAULTS = {
    "GUEST": [KYC_SUBMIT],
    "HOST": [
        PROPERTY_CREATE, PROPERTY_UPDATE, BOOKING_VIEW, BOOKING_CANCEL,
        PAYMENT_VIEW, PAYOUT_REQUEST, KYC_SUBMIT,
    ],
    "STAFF": [
        USER_VIEW, PROPERTY_VIEW_ALL, BOOKING_VIEW_ALL, PAYMENT_VIEW_ALL,
        PAYOUT_VIEW_ALL, KYC_REVIEW, KYC_VIEW_ALL, REVIEW_MODERATE,
        DISPUTE_MANAGE, AUDIT_VIEW, ANALYTICS_VIEW,
    ],
    "ADMIN": [
        USER_VIEW, USER_UPDATE, USER_MANAGE,
        PROPERTY_VIEW_ALL, PROPERTY_APPROVE, PROPERTY_SUSPEND,
        BOOKING_VIEW_ALL, BOOKING_CANCEL,
        PAYMENT_VIEW_ALL, PAYMENT_REFUND,
        PAYOUT_APPROVE, PAYOUT_VIEW_ALL,
        KYC_REVIEW, KYC_VIEW_ALL,
        REVIEW_MODERATE, DISPUTE_MANAGE,
        LOCATION_MANAGE, AMENITY_MANAGE, SETTINGS_UPDATE,
        PROMOTION_MANAGE, TAX_MANAGE, NOTIFICATION_TEMPLATE_MANAGE,
        AUDIT_VIEW, ANALYTICS_VIEW, SECURITY_VIEW, INCIDENT_MANAGE,
    ],
    "SUPER_ADMIN": ALL_CODES,
}

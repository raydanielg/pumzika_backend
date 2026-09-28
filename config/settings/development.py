from .base import *  # noqa: F401,F403

DEBUG = env_bool("DEBUG", True)

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Browsable API in development alongside the envelope renderer.
REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = (  # noqa: F405
    "apps.common.renderers.EnvelopeJSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
)

if env_bool("ENABLE_DEBUG_TOOLBAR", False):  # noqa: F405
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE.insert(0, "debug_toolbar.middleware.DebugToolbarMiddleware")  # noqa: F405
    INTERNAL_IPS = ["127.0.0.1"]

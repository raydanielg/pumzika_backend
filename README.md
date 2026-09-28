# Pumzika Africa — Backend

Production-oriented backend for **Pumzika Africa**, an African short-stay
accommodation marketplace. Modular Django monolith, API-first, built to start
in Tanzania and expand across Africa.

## Stack

- Python 3.12+, Django 5, Django REST Framework
- PostgreSQL · Redis · Celery
- JWT (SimpleJWT, rotating refresh + blacklist)
- drf-spectacular (OpenAPI/Swagger)
- S3-compatible object storage (django-storages) / local media in dev
- Gunicorn · Docker · docker-compose

## Architecture

```
config/                  project config (settings/base|development|production, urls, celery)
apps/
  accounts/              custom User, roles, permission codes, OTP verification
  locations/             Country -> Region -> City -> District -> Area
  properties/            listings, media, amenities, rules, policies, documents
  kyc/                   identity verification workflow + staff review
  availability/          per-date calendar; unique (property, date) rows
  bookings/              state machine, price snapshots, cancellation engine
  payments/              provider abstraction, transactions, refunds, webhooks
  payouts/               host wallet (append-only ledger) + payout workflow
  reviews/               property/host/guest reviews (completed stays only)
  messaging/             guest-host conversations
  notifications/         in-app/email/SMS/push, templates, preferences, tasks
  favorites/             saved listings
  promotions/            promo codes with scopes/limits
  disputes/              dispute workflow + resolution
  search/                filtered/geo/date-aware property search
  analytics/             event tracking + dashboard aggregates
  admin_panel/           settings, commission/tax rules, audit log, admin API
  common/                envelope responses, errors, pagination, middleware,
                         logging, storage backends, validators, health checks
tests/                   integration + business-logic tests
requirements/            base / development / production pins
```

### Key design decisions

- **Business config lives in the database** (`PlatformSetting`,
  `CommissionRule`, `TaxRule`, `CancellationPolicy`, `PaymentProvider`,
  `PropertyType`, `Amenity`) — nothing country/fee/provider-specific is
  hardcoded.
- **Permissions are codes** (`properties.approve`, `kyc.review`, ...)
  granted to roles via `RolePermission`, enforced by
  `common.permissions.PermissionRequired` on every protected endpoint.
- **Double-booking guarantee**: booking creation locks the property row in a
  transaction, checks availability, and writes one `AvailabilityDate` row per
  night. The DB `unique(property, date)` constraint makes concurrent
  double-booking impossible even if the lock were bypassed.
- **Money is Decimal end-to-end.** Prices are computed only by the booking
  pricing engine and snapshotted into `BookingPrice` — later host price
  changes never mutate existing bookings. Commission rate is snapshotted too.
- **Payments are pluggable**: `PaymentProviderInterface` + registry. `MOCK`
  is a clearly-labelled sandbox provider (HMAC-signed webhooks); real
  providers implement the same interface. Payment status comes only from
  signature-verified webhooks, deduplicated by `(provider, event_id)`.
- **Ledger immutability**: `WalletTransaction` and `PaymentTransaction` are
  append-only; corrections are reversal rows.
- **Audit**: `admin_panel.services.audit()` writes `AuditLog` rows for
  security/admin/financial actions with actor, IP, before/after.
- **Every response** follows the envelope:
  `{success, data, message, request_id}` / `{success:false, error:{code,...}}`.

## Requirements

- Python 3.12+, PostgreSQL 14+, Redis 6+
- (or just Docker + docker-compose)

## Quickstart (local)

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements/development.txt

cp .env.example .env            # edit as needed
createdb pumzika                # or set DATABASE_URL in .env

python manage.py migrate
python manage.py seed_dev       # TZ data, amenities, policies, dev users
python manage.py seed_demo      # the above + 3 published demo listings
python manage.py runserver
```

Dev seed users (do **not** deploy these passwords):

| Email              | Role        |
|--------------------|-------------|
| admin@pumzika.dev  | SUPER_ADMIN |
| host@pumzika.dev   | HOST        |
| guest@pumzika.dev  | GUEST       |

### Celery

```bash
celery -A config worker --loglevel=info
celery -A config beat   --loglevel=info   # expiry sweeps + reminders
```

### Tests

```bash
python manage.py test tests          # 68 tests: bookings, payments, KYC, ...
python manage.py check
python manage.py makemigrations --check   # verify no model drift
```

### Idempotency

`POST /api/v1/bookings/`, `POST /api/v1/payments/initiate/`,
`POST /api/v1/payouts/` and `POST /api/v1/payments/refunds/create/` accept an
`Idempotency-Key` header — a retried request returns the original record
rather than creating a duplicate.

### Property moderation

`DRAFT → SUBMITTED → UNDER_REVIEW → APPROVED → PUBLISHED` — hosts submit
(`POST /api/v1/properties/{id}/submit_review/`), staff approve/reject via
`/api/v1/admin/properties/{id}/approve|reject|suspend/`, and hosts publish
with `POST /api/v1/properties/{id}/publish/`. A rejected/suspended action
requires a `reason`. Submission returns field-level errors
(`PROPERTY_INCOMPLETE.details`).

### Location privacy

Public listings expose `approximate_latitude`/`approximate_longitude`
(~1 km rounding) and no street address. The exact `address` + coordinates
appear on a booking only once it reaches `CONFIRMED`.

### Devices & sessions

`POST /api/v1/notifications/devices/` registers a push device (users can have
many). `GET /api/v1/users/me/sessions/` lists active login sessions;
`POST /api/v1/users/me/sessions/revoke-all/` or
`…/sessions/<jti>/revoke/` revokes them.

### API docs

- Swagger UI: `http://localhost:8000/api/docs/`
- OpenAPI schema: `http://localhost:8000/api/schema/`

### Health checks

`GET /health/` · `GET /health/db/` · `GET /health/redis/`

## Docker

```bash
cd backend
cp .env.example .env
docker compose up --build      # web + celery + celery-beat + postgres + redis
docker compose exec web python manage.py seed_dev
```

Web listens on `:8000`. Gunicorn is the production command baked into the
Dockerfile (`config/wsgi.py` defaults to `config.settings.production`).

## Payments (sandbox)

`MOCK` provider is seeded and active in development. Flow:

1. `POST /api/v1/bookings/` — creates a `PENDING` booking and locks dates.
2. `POST /api/v1/payments/initiate/` — `{booking_id, provider:"MOCK",
   idempotency_key:"<uuid>"}` — returns a checkout URL + `PAY-…` reference.
3. Provider calls `POST /api/v1/payments/webhooks/MOCK/` with an HMAC
   (`X-Webhook-Signature`) — `payment.success` confirms the booking; a replay
   is a verified no-op.

Real providers (Selcom, AzamPay, Stripe) plug in via `providers.py` and are
enabled/configured in the `PaymentProvider` table; credentials come from env
vars, never the DB.

## Environment variables

See `.env.example` — every environment-specific value (DB, Redis, JWT, CORS,
storage, email, SMS, payment credentials) is read from env. Business values
(commission, service fee, taxes, limits) are `PlatformSetting`/`TaxRule`/
`CommissionRule` rows managed via the admin API.

## Security notes

- Argon2 password hashing; JWT access/refresh with rotation + blacklist on
  logout; auth-sensitive endpoints are rate-limited.
- Object-level authorization everywhere (host↔guest isolation, participant-
  only messaging, booking-party-only disputes).
- KYC/property documents use private storage — never served publicly.
- Webhook payloads are signature-verified, hashed and deduplicated.
- Audit metadata scrubs keys that look like credentials.
- `config/settings/production.py` enforces SSL, HSTS, secure cookies, etc.

## Layout decisions worth knowing

- `Booking.status` transitions are a declared state machine
  (`Booking.TRANSITIONS`) — invalid jumps raise `INVALID_BOOKING_TRANSITION`.
- Unpaid bookings expire via a Celery sweep (`expire_unpaid_bookings`) which
  releases the locked dates.
- Host payout flow: completed booking → `EARNING` wallet credit →
  `Payout` request → admin approval → `COMPLETED`; rejection posts a
  `REVERSAL` credit.

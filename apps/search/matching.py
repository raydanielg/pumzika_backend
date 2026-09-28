"""Smart Stay Match — deterministic matching over real inventory.

Pipeline:
  1. Hard filters at the DB level (published, destination, capacity,
     budget ceiling, live availability via AvailabilityDate).
  2. Transparent weighted scoring on the surviving page of candidates.
  3. Human-readable label + factual explanations only.

No ML, no fabricated signals — every score component maps to real data.
Weights are centralized in WEIGHTS so they can move to settings later.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q

from apps.availability.models import AvailabilityDate, AvailabilityStatus
from apps.bookings.pricing import compute_quote
from apps.properties.models import Property

BLOCKING = [
    AvailabilityStatus.UNAVAILABLE,
    AvailabilityStatus.BLOCKED,
    AvailabilityStatus.MAINTENANCE,
]

# Preference → keywords matched against real property data only:
# property_type name/code, amenity names, title/description, area/city names.
PREFERENCE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "beach": ("beach", "beachfront", "sea", "ocean", "coast", "seaside", "island"),
    "city": ("apartment", "studio", "loft", "city", "downtown", "cbd", "central"),
    "quiet": ("quiet", "garden", "retreat", "cottage", "village", "peaceful"),
    "family": ("family", "kids", "children", "playground", "crib", "spacious"),
    "business": ("wifi", "workspace", "desk", "work", "apartment", "business"),
    "romantic": ("romantic", "honeymoon", "suite", "jacuzzi", "couple", "private"),
    "adventure": ("adventure", "safari", "hiking", "mountain", "climb", "trek"),
    "nature": ("nature", "forest", "garden", "farm", "eco", "park", "view"),
    "luxury": ("luxury", "pool", "villa", "premium", "deluxe", "penthouse"),
    "budget": ("hostel", "guesthouse", "budget", "homestay", "backpacker"),
}

# Centralized, inspectable weights — total 100.
WEIGHTS = {
    "budget_fit": 25,
    "preference": 35,  # split evenly across the guest's chosen preferences
    "capacity_fit": 15,
    "quality": 15,     # rating + review depth
    "trust": 10,       # verified host + photos present
}

LABELS = (
    (75, "great_match"),
    (50, "good_match"),
    (0, "fits_your_trip"),
)


@dataclass
class MatchResult:
    property: Property
    score: int
    label: str
    reasons: list[str] = field(default_factory=list)
    total_price: Decimal | None = None
    currency: str = ""


def _haystack(prop: Property) -> str:
    """All real text signals for one property, lowercased."""
    amenity_names = " ".join(a.name for a in prop.amenities.all())
    parts = [
        prop.title, prop.description or "",
        prop.property_type.name if prop.property_type else "",
        prop.city.name if prop.city else "",
        prop.district.name if prop.district else "",
        prop.area.name if prop.area else "",
        amenity_names,
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _candidate_queryset(params: dict):
    """Hard filters — every property that survives is genuinely bookable."""
    qs = (
        Property.objects.filter(status=Property.Status.PUBLISHED)
        .select_related("property_type", "country", "region", "city",
                        "district", "area", "host__host_profile")
        .prefetch_related("images", "amenities", "units")
    )
    destination = params.get("destination")
    if destination:
        qs = qs.filter(
            Q(title__icontains=destination)
            | Q(city__name__icontains=destination)
            | Q(region__name__icontains=destination)
            | Q(district__name__icontains=destination)
            | Q(area__name__icontains=destination)
        )
    guests = params["guests"]
    qs = qs.filter(
        Q(max_guests__gte=guests)
        | Q(units__is_active=True, units__max_guests__gte=guests)
    ).distinct()

    budget = params.get("budget_per_night")
    if budget is not None:
        # Cheapest active unit price can undercut the property base price.
        qs = qs.filter(
            Q(base_price__lte=budget)
            | Q(units__is_active=True, units__price_per_night__lte=budget)
        ).distinct()

    check_in, check_out = params.get("check_in"), params.get("check_out")
    if check_in and check_out:
        nights = (check_out - check_in).days
        # Property-level blocking rows rule the property out entirely.
        blocked_ids = AvailabilityDate.objects.filter(
            unit__isnull=True,
            date__gte=check_in, date__lt=check_out,
            status__in=BLOCKING,
        ).values("property_id")
        qs = qs.exclude(id__in=blocked_ids)
        qs = qs.filter(
            Q(units__isnull=True)  # whole-property listing — already checked
            | Q(units__is_active=True)
        ).distinct()
        qs = qs.filter(min_nights__lte=nights)
        qs = qs.filter(
            Q(max_nights__isnull=True) | Q(max_nights__gte=nights)
        )
    return qs


def _score(prop: Property, params: dict) -> tuple[int, list[str]]:
    """Transparent score 0-100 + factual reasons. Nothing invented."""
    reasons: list[str] = []
    points = 0.0

    # Budget fit — full points when the cheapest nightly rate fits the budget.
    budget = params.get("budget_per_night")
    if budget is not None:
        unit_prices = [
            u.price_per_night for u in prop.units.all()
            if u.is_active and u.price_per_night is not None
        ]
        nightly = min(unit_prices) if unit_prices else prop.base_price
        if nightly <= budget:
            points += WEIGHTS["budget_fit"]
            reasons.append("Within your budget")
        elif nightly <= budget * Decimal("1.15"):
            points += WEIGHTS["budget_fit"] * 0.5
            reasons.append("Slightly above your budget")

    # Preferences — score is the share of chosen preferences that matched.
    prefs = params.get("preferences") or []
    if prefs:
        text = _haystack(prop)
        hits = [p for p in prefs
               if any(k in text for k in PREFERENCE_KEYWORDS.get(p, (p,)))]
        if hits:
            share = len(hits) / len(prefs)
            points += WEIGHTS["preference"] * share
            for p in hits:
                reasons.append(f"Suits a {p.replace('-', ' ')} stay")
    else:
        points += WEIGHTS["preference"]  # nothing requested — no penalty

    # Capacity fit — closest fit above the guest count scores best.
    guests = params["guests"]
    headroom = prop.max_guests - guests
    if headroom >= 0:
        points += WEIGHTS["capacity_fit"] if headroom <= 2 else \
            WEIGHTS["capacity_fit"] * 0.7
        reasons.append(f"Sleeps {prop.max_guests} guests")

    # Quality signals — rating and review depth, only when real.
    rating = float(prop.rating or 0)
    reviews = prop.review_count or 0
    if rating >= 4.5 and reviews >= 3:
        points += WEIGHTS["quality"]
        reasons.append(f"Rated {rating:g} by {reviews} guests")
    elif rating >= 4.0:
        points += WEIGHTS["quality"] * 0.6
        reasons.append(f"Rated {rating:g}")

    # Trust signals.
    profile = getattr(prop.host, "host_profile", None)
    verified = bool(
        profile and profile.verification_status == "VERIFIED"
    )
    has_photos = any(True for _ in prop.images.all())
    trust_share = (0.6 if verified else 0) + (0.4 if has_photos else 0)
    points += WEIGHTS["trust"] * trust_share
    if verified:
        reasons.append("Verified host")

    if params.get("check_in"):
        reasons.insert(0, "Available for your dates")

    return min(100, round(points)), reasons


def _label(score: int) -> str:
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return "fits_your_trip"


def _price(prop: Property, check_in, check_out) -> Decimal | None:
    """Authoritative total via the pricing engine — never duplicated here."""
    if not (check_in and check_out):
        return None
    try:
        cheapest_unit = min(
            (u for u in prop.units.all()
             if u.is_active and u.price_per_night is not None),
            key=lambda u: u.price_per_night, default=None,
        )
        breakdown = compute_quote(prop, check_in, check_out, unit=cheapest_unit)
        return breakdown.total
    except Exception:  # noqa: BLE001 — pricing edge (specials/overrides)
        return None


def _sold_out_unit_ids(properties, check_in, check_out) -> set:
    """One query: per (unit, night) BOOKED counts -> units at capacity."""
    unit_map = {}
    for prop in properties:
        for u in prop.units.all():
            if u.is_active:
                unit_map[u.id] = u.quantity
    if not unit_map:
        return set()
    booked = (
        AvailabilityDate.objects.filter(
            unit_id__in=unit_map.keys(),
            date__gte=check_in, date__lt=check_out,
            status=AvailabilityStatus.BOOKED,
        )
        .values("unit_id", "date")
        .annotate(n=Count("id"))
    )
    sold = set()
    for row in booked:
        if row["n"] >= unit_map[row["unit_id"]]:
            sold.add(row["unit_id"])
    return sold


def match_stays(params: dict, limit: int = 60) -> list[MatchResult]:
    """Score + rank candidates. Limited pool — ranking beyond the head
    of the list has no guest value and wastes pricing calls."""
    qs = _candidate_queryset(params)
    check_in, check_out = params.get("check_in"), params.get("check_out")

    properties = list(qs[:limit])
    if check_in and check_out:
        sold_out = _sold_out_unit_ids(properties, check_in, check_out)
        properties = [
            p for p in properties
            if not p.units.all().exists()
            or any(u.is_active and u.id not in sold_out
                   for u in p.units.all())
        ]

    results = [
        MatchResult(property=p, score=s, label=_label(s), reasons=r)
        for p in properties
        for s, r in [_score(p, params)]
    ]
    sort = params.get("sort") or "recommended"
    if sort == "price_asc":
        results.sort(key=lambda m: m.property.base_price)
    elif sort == "price_desc":
        results.sort(key=lambda m: -m.property.base_price)
    elif sort == "rating":
        results.sort(key=lambda m: (m.property.rating or 0,
                                    m.property.review_count or 0),
                     reverse=True)
    else:
        results.sort(key=lambda m: m.score, reverse=True)

    # Price only the surviving candidates through the real pricing engine.
    for r in results:
        r.total_price = _price(r.property, check_in, check_out)
        r.currency = r.property.currency
    return results


def suggest_adjustments(params: dict) -> list[dict]:
    """Honest next-best moves when nothing matched. Each suggestion
    describes a concrete relaxation — the client decides."""
    suggestions = []
    if params.get("budget_per_night"):
        cheaper = (
            Property.objects.filter(status=Property.Status.PUBLISHED)
            .order_by("base_price")
            .values_list("base_price", flat=True)
            .first()
        )
        if cheaper and cheaper > params["budget_per_night"]:
            suggestions.append({
                "type": "raise_budget",
                "min_price": str(cheaper),
            })
    if params.get("preferences"):
        suggestions.append({"type": "remove_preference"})
    if params.get("check_in"):
        suggestions.append({"type": "change_dates"})
    if params.get("destination"):
        suggestions.append({"type": "expand_destination"})
    return suggestions

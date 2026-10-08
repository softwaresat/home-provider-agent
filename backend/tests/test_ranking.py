from app.models import Provider, ServiceCategory
from app.ranking import rank_providers, score_provider


def _provider(**kwargs) -> Provider:
    base = dict(
        place_id="abc",
        name="Test Plumbing",
        address="Austin, TX 78704",
        phone="512-555-0100",
        website="https://example.com",
        rating=4.6,
        review_count=80,
        primary_type="plumber",
        is_service_area_business=False,
        source="google_places",
    )
    base.update(kwargs)
    return Provider(**base)


def test_type_match_outscores_unrelated_listing():
    plumber = _provider(place_id="p1", name="A1 Plumbing", primary_type="plumber")
    bakery = _provider(
        place_id="p2",
        name="Austin Bakery",
        primary_type="bakery",
        phone="512-555-0199",
        rating=5.0,
        review_count=400,
    )
    ranked = rank_providers([bakery, plumber], ServiceCategory.plumbing, "Austin", "78704")
    assert ranked[0].place_id == "p1"
    assert ranked[0].match_score > ranked[1].match_score
    assert any("matches plumbing" in reason for reason in ranked[0].match_reasons)


def test_phone_adds_points():
    with_phone = score_provider(
        _provider(phone="512-555-0100"),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    without_phone = score_provider(
        _provider(phone=None, place_id="x2", name="No Phone Plumbing"),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    assert with_phone.match_score >= without_phone.match_score + 2
    assert any("Phone number" in reason for reason in with_phone.match_reasons)


def test_service_area_business_reason():
    sab = score_provider(
        _provider(
            address=None,
            is_service_area_business=True,
            name="Mobile Plumber",
        ),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    assert any("service area not confirmed" in reason.lower() for reason in sab.match_reasons)


def test_business_name_confirms_trade_for_general_contractor_listing():
    restoration = score_provider(
        _provider(
            name="PuroClean of Northwest Austin",
            primary_type="general_contractor",
            primary_type_display="General Contractor",
        ),
        ServiceCategory.water_damage,
        "Austin",
        "78717",
    )
    unrelated = score_provider(
        _provider(
            place_id="g2",
            name="Smith Builders",
            primary_type="general_contractor",
            primary_type_display="General Contractor",
        ),
        ServiceCategory.water_damage,
        "Austin",
        "78717",
    )
    restoration_named = score_provider(
        _provider(
            place_id="g3",
            name="Austin Water Damage & Restoration",
            primary_type="general_contractor",
        ),
        ServiceCategory.water_damage,
        "Austin",
        "78717",
    )
    assert any("name indicates water damage" in r for r in restoration_named.match_reasons)
    assert restoration_named.match_score >= unrelated.match_score + 2
    assert not any("not confirmed" in r for r in restoration_named.match_reasons)
    assert any("not confirmed" in r for r in unrelated.match_reasons)
    assert restoration.match_score <= restoration_named.match_score


def test_out_of_area_phone_on_no_address_listing_is_flagged():
    local_a = _provider(place_id="l1", name="Austin Flood Co", address="1 Main St, Austin, TX", phone="(512) 555-0101")
    local_b = _provider(place_id="l2", name="Texas Restoration", address="2 Main St, Austin, TX", phone="(737) 555-0102")
    national = _provider(
        place_id="n1",
        name="A1 Restoration",
        address=None,
        is_service_area_business=True,
        phone="(480) 773-0211",
        rating=5.0,
        review_count=590,
    )
    ranked = rank_providers([national, local_a, local_b], ServiceCategory.water_damage, "Austin", "78717")
    flagged = next(p for p in ranked if p.place_id == "n1")
    assert any("(480)" in r and "national call center" in r for r in flagged.match_reasons)
    assert ranked[-1].place_id == "n1"
    assert not any("call center" in r for p in ranked if p.place_id != "n1" for r in p.match_reasons)


def test_score_sets_trade_and_contact_flags():
    plumber = score_provider(
        _provider(primary_type="plumber", phone="512-555-0100"),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    bakery = score_provider(
        _provider(
            place_id="b1",
            name="Austin Bakery",
            primary_type="bakery",
            phone=None,
            website=None,
            maps_url=None,
        ),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    assert plumber.trade_confirmed is True
    assert plumber.contactable is True
    assert bakery.trade_confirmed is False
    assert bakery.contactable is False


def test_city_and_zip_in_address_add_geo_points():
    local = score_provider(
        _provider(address="123 Main St, Austin, TX 78704"),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    other = score_provider(
        _provider(place_id="o", name="Dallas Plumbing", address="Dallas, TX 75201"),
        ServiceCategory.plumbing,
        "Austin",
        "78704",
    )
    assert local.match_score >= other.match_score + 1

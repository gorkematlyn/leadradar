from leadradar.modules.crm.normalize import (
    detect_social,
    name_similarity,
    normalize_domain,
    normalize_name,
    normalize_phone,
    normalize_url,
)


def test_domain_normalization_handles_www_case_tracking_and_fragments():
    n = normalize_url("HTTPS://WWW.Example.co.uk/path?utm_source=x&id=3#frag")
    assert n is not None
    assert n.canonical_domain == "example.co.uk"
    assert n.url == "https://www.example.co.uk/path?id=3"
    assert normalize_domain("example.co.uk") == normalize_domain("http://www.example.co.uk/")


def test_idn_domains_are_punycoded():
    assert normalize_domain("http://münchen-zahnarzt.de") == "xn--mnchen-zahnarzt-zvb.de"


def test_shared_platforms_do_not_collapse_identity():
    a = normalize_url("https://facebook.com/acme")
    b = normalize_url("https://facebook.com/other")
    assert a and b and a.is_shared_platform
    assert a.property_key != b.property_key


def test_public_suffix_private_domains_keep_subdomain():
    a = normalize_url("https://shop-one.myshopify.com")
    b = normalize_url("https://shop-two.myshopify.com")
    assert a and b and a.canonical_domain != b.canonical_domain


def test_meaningful_subdomain_preserved_in_property_key():
    n = normalize_url("https://istanbul.example.com.tr/")
    assert n and n.canonical_domain == "example.com.tr" and n.property_key == "istanbul.example.com.tr"


def test_invalid_urls_rejected():
    for v in ["", "mailto:a@b.c", "javascript:alert(1)", "localhost", "ftp://example.com"]:
        assert normalize_url(v) is None


def test_phone_normalization():
    assert normalize_phone("0212 555 11 22", "TR") == "+902125551122"
    assert normalize_phone("+31 (0)20 1234567") == "+31201234567"
    assert normalize_phone("(415) 555-0100", "US") == "+14155550100"
    assert normalize_phone("abc") is None


def test_name_normalization_and_similarity():
    assert normalize_name("Acme Diş Kliniği Ltd. Şti.") == "acme dis klinigi"
    assert name_similarity("Acme Dental GmbH", "ACME Dental") == 1.0
    assert name_similarity("Acme Dental", "Blue Bakery") == 0.0


def test_social_detection_excludes_personal_profiles():
    assert detect_social("https://www.instagram.com/acme.dental/") == ("instagram", "acme.dental")
    assert detect_social("https://linkedin.com/company/acme") == ("linkedin", "company/acme")
    assert detect_social("https://linkedin.com/in/john-doe") is None
    assert detect_social("https://facebook.com/sharer/sharer.php?u=x") is None

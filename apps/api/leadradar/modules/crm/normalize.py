"""Deterministic normalization of domains, URLs, names and telephone numbers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import idna
import tldextract

# Offline extractor: bundled Public Suffix List snapshot, private suffixes included so
# that e.g. "shop.myshopify.com" or "user.github.io" keep their meaningful subdomain.
_extract = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)

TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z_]+|gclid|gbraid|wbraid|fbclid|msclkid|ttclid|li_fat_id|mc_cid|mc_eid|_ga|_gl|yclid|igshid|ref|ref_src)$",
    re.I,
)

# Domains that host many unrelated businesses: never treat a shared registrable domain
# as identity. Subdomain or path identifies the business on these.
SHARED_PLATFORM_DOMAINS = {
    "facebook.com", "fb.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "tiktok.com",
    "youtube.com", "pinterest.com", "google.com", "goo.gl", "g.page", "business.site", "sites.google.com",
    "wixsite.com", "wix.com", "squarespace.com", "weebly.com", "wordpress.com", "blogspot.com",
    "tumblr.com", "linktr.ee", "linkin.bio", "beacons.ai", "carrd.co", "jimdosite.com", "jimdofree.com",
    "webnode.com", "yola.com", "strikingly.com", "godaddysites.com", "ueniweb.com", "booking.com",
    "tripadvisor.com", "yelp.com", "trendyol.com", "hepsiburada.com", "n11.com", "amazon.com", "etsy.com",
    "ebay.com", "sahibinden.com", "doctolib.de", "doctoralia.com", "doktortakvimi.com", "treatwell.com",
    "fresha.com", "opentable.com", "thefork.com", "airbnb.com", "whatsapp.com", "wa.me", "t.me",
}

SOCIAL_PLATFORMS = {
    "facebook.com": "facebook", "fb.com": "facebook", "instagram.com": "instagram",
    "linkedin.com": "linkedin", "twitter.com": "x", "x.com": "x", "tiktok.com": "tiktok",
    "youtube.com": "youtube", "pinterest.com": "pinterest",
}


@dataclass(frozen=True)
class NormalizedUrl:
    url: str  # cleaned absolute URL
    host: str  # punycode host without www
    registrable_domain: str  # e.g. example.co.uk
    canonical_domain: str  # identity key: registrable domain, or full host on shared platforms
    is_shared_platform: bool
    property_key: str  # canonical_domain + meaningful path prefix (for shared platforms)


def _to_ascii(host: str) -> str:
    host = host.strip().rstrip(".").lower()
    if not host.isascii():
        host = idna.encode(host, uts46=True).decode()
    return host


def normalize_url(raw: str) -> NormalizedUrl | None:
    """Clean a website value from any source. Returns None when it is not a usable URL."""
    if not raw:
        return None
    raw = raw.strip().split()[0] if raw.strip() else ""
    if not raw or raw.startswith(("mailto:", "tel:", "javascript:")):
        return None
    if "://" not in raw:
        raw = "http://" + raw.lstrip("/")
    try:
        parts = urlsplit(raw)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return None
        host = _to_ascii(parts.hostname)
    except (ValueError, idna.IDNAError):
        return None
    if "." not in host:
        return None
    bare = host[4:] if host.startswith("www.") else host
    ext = _extract(bare)
    if not ext.suffix or not ext.domain:
        return None
    registrable = f"{ext.domain}.{ext.suffix}"
    shared = registrable in SHARED_PLATFORM_DOMAINS or bare in SHARED_PLATFORM_DOMAINS
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not TRACKING_PARAMS.match(k)]
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    cleaned = urlunsplit((parts.scheme.lower(), host + port, path, urlencode(query), ""))
    if shared:
        # Keep subdomain (shop.wixsite.com) and first path segment (facebook.com/acme).
        segment = path.strip("/").split("/")[0].lower() if path.strip("/") else ""
        canonical = bare
        prop = f"{bare}/{segment}" if segment else bare
    else:
        # A meaningful subdomain other than www (e.g. "istanbul.example.com") is preserved
        # in the property key, but the canonical identity is the registrable domain.
        canonical = registrable
        prop = bare
    return NormalizedUrl(cleaned, bare, registrable, canonical, shared, prop)


def normalize_domain(raw: str) -> str | None:
    n = normalize_url(raw)
    return n.canonical_domain if n else None


_LEGAL_SUFFIXES = re.compile(
    r"\b(ltd|limited|llc|inc|corp|co|gmbh|ag|kg|ug|bv|b\.v|nv|sa|sas|sarl|srl|spa|plc|lp|llp|"
    r"a\.s|a\.ş|aş|as|ltd\.?\s*şti|şti|sti|tic|san|ve|and|the)\b\.?",
    re.I,
)


def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "")
    s = s.replace("ı", "i").replace("İ", "i")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("&", " and ")
    s = _LEGAL_SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_COUNTRY_CALLING = {"TR": "90", "NL": "31", "DE": "49", "GB": "44", "US": "1", "FR": "33", "ES": "34", "IT": "39"}


def normalize_phone(raw: str | None, country_iso2: str | None = None) -> str | None:
    """Return E.164-like digits with leading '+', or None. Deterministic, no network."""
    if not raw:
        return None
    first = re.split(r"[;,/]| or ", raw)[0].replace("(0)", "")
    digits = re.sub(r"[^\d+]", "", first)
    if not digits:
        return None
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    if digits.startswith("+"):
        d = "+" + re.sub(r"\D", "", digits)
    else:
        cc = _COUNTRY_CALLING.get((country_iso2 or "").upper())
        if not cc:
            d = re.sub(r"\D", "", digits)
            return d if len(d) >= 7 else None
        local = re.sub(r"\D", "", digits)
        if cc != "1" and local.startswith("0"):
            local = local[1:]
        if cc == "1" and len(local) == 11 and local.startswith("1"):
            local = local[1:]
        d = f"+{cc}{local}"
    return d if 8 <= len(d) <= 16 else None


def detect_social(url: str) -> tuple[str, str] | None:
    """(platform, handle) for business social profile URLs."""
    n = normalize_url(url)
    if not n:
        return None
    platform = SOCIAL_PLATFORMS.get(n.registrable_domain)
    if not platform:
        return None
    path = urlsplit(n.url).path.strip("/")
    if not path:
        return None
    segs = path.split("/")
    if platform == "linkedin" and len(segs) >= 2 and segs[0] in {"company", "school", "showcase"}:
        return platform, f"{segs[0]}/{segs[1].lower()}"
    if platform == "linkedin":
        return None  # personal profiles (/in/...) are intentionally not collected
    handle = segs[0].lstrip("@").lower()
    if handle in {"sharer", "share", "intent", "plugins", "dialog", "watch", "p", "reel", "hashtag", "pages", "profile.php"}:
        return None
    return platform, handle


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def name_similarity(a: str, b: str) -> float:
    """Token-set Jaccard similarity on normalized names (0..1)."""
    ta, tb = set(normalize_name(a).split()), set(normalize_name(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

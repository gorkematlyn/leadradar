"""Static HTML checks (SEO, structure, conversion, contact). Deterministic; no rendering."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node

from leadradar.modules.website_audit.results import (
    DETECTED,
    FAILED,
    NOT_APPLICABLE,
    NOT_DETECTED,
    PASSED,
    UNKNOWN,
    EvidenceItem,
    RuleResult,
)

PARKED_PATTERNS = [
    r"this domain (?:is|may be) for sale", r"buy this domain", r"domain is parked", r"parked (?:free|domain)",
    r"sedoparking", r"bodis\.com", r"parkingcrew", r"dan\.com/buy-domain", r"hugedomains", r"afternic",
    r"bu alan ad[ıi] sat[ıi]l[ıi]kt[ıi]r", r"godaddy\.com/domainsearch", r"domain parking",
]
MAINTENANCE_PATTERNS = [
    r"under construction", r"coming soon", r"under maintenance", r"site is (?:currently )?(?:down for|under) maintenance",
    r"yap[ıi]m a[şs]amas[ıi]nda", r"bak[ıi]m(?:dad[ıi]r| çal[ıi][şs]mas[ıi])", r"[çc]ok yak[ıi]nda",
    r"wartungsarbeiten", r"in wartung", r"binnenkort online", r"website in aanbouw",
]
CONTACT_WORDS = r"contact|iletişim|iletisim|kontakt|bize ulaşın|ulaşın|contacto|contatti|neem contact"
BOOKING_PATTERNS = [
    r"book(?:ing| now| an? appointment| online)", r"appointment", r"randevu", r"rezervasyon", r"reserv(?:e|ation)",
    r"termin (?:buchen|vereinbaren)", r"afspraak", r"calendly\.com", r"doctolib", r"opentable", r"thefork", r"resy\.com",
    r"booking\.com", r"simplybook", r"setmore", r"acuityscheduling", r"treatwell", r"fresha\.com", r"doktortakvimi",
    r"cloudbeds", r"siteminder", r"mews\.com", r"hotelrunner", r"sirvoy",
]
QUOTE_PATTERNS = [r"request a quote", r"get a quote", r"quote request", r"teklif (?:al|iste|formu)", r"fiyat teklifi",
                  r"angebot anfordern", r"offerte aanvragen", r"rfq", r"product inquiry", r"ürün talep"]
CTA_PATTERNS = [r"\bcall\b", r"contact us", r"get started", r"book", r"order", r"buy", r"shop now", r"request",
                r"sign up", r"hemen", r"ara(?:yın)?\b", r"teklif", r"randevu", r"sipariş", r"satın al", r"jetzt",
                r"anfragen", r"bestellen", r"bel ons", r"bestel"]
ECOMMERCE_PATTERNS = [r"add[ -]to[ -]cart", r"sepete ekle", r"in den warenkorb", r"winkelwagen", r"woocommerce",
                      r"cdn\.shopify\.com", r"shopify\.theme", r"/cart\b", r"/sepet\b", r"product-price", r"itemprop=\"price\"",
                      r"ideasoft", r"ticimax", r"magento", r"prestashop", r"shopware", r"bigcommerce", r"ikas"]
CHECKOUT_PATTERNS = [r"/checkout\b", r"/odeme\b", r"/kasse\b", r"stripe\.com/v3", r"iyzico", r"paytr", r"paypal\.com/sdk",
                     r"klarna", r"adyen", r"mollie"]
PLATFORMS = [
    ("wordpress", "WordPress", [r"/wp-content/", r"/wp-includes/", r"<meta name=\"generator\" content=\"WordPress"]),
    ("shopify", "Shopify", [r"cdn\.shopify\.com", r"Shopify\.theme", r"myshopify\.com"]),
    ("wix", "Wix", [r"static\.wixstatic\.com", r"<meta name=\"generator\" content=\"Wix", r"wix-bolt"]),
    ("squarespace", "Squarespace", [r"static1\.squarespace\.com", r"Squarespace\."]),
    ("webflow", "Webflow", [r"assets\.website-files\.com", r"data-wf-site", r"<meta content=\"Webflow\" name=\"generator\""]),
    ("joomla", "Joomla", [r"/media/jui/", r"<meta name=\"generator\" content=\"Joomla"]),
    ("drupal", "Drupal", [r"/sites/default/files/", r"Drupal\.settings", r"<meta name=\"Generator\" content=\"Drupal"]),
    ("woocommerce", "WooCommerce", [r"woocommerce"]),
    ("magento", "Magento", [r"/static/version\d+/frontend/", r"Mage\.Cookies"]),
    ("prestashop", "PrestaShop", [r"prestashop"]),
    ("ideasoft", "IdeaSoft", [r"ideasoft"]),
    ("ticimax", "Ticimax", [r"ticimax"]),
    ("ikas", "ikas", [r"cdn\.myikas\.com"]),
    ("next", "Next.js", [r"/_next/static/"]),
    ("gatsby", "Gatsby", [r"___gatsby"]),
    ("elementor", "Elementor", [r"elementor-"]),
]


@dataclass
class PageInfo:
    url: str
    html: str
    tree: HTMLParser
    internal_links: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    text: str = ""
    lang: str | None = None
    tel_links: list[str] = field(default_factory=list)
    mailto_links: list[str] = field(default_factory=list)
    whatsapp_links: list[str] = field(default_factory=list)
    social_links: list[str] = field(default_factory=list)
    contact_links: list[str] = field(default_factory=list)
    forms: list[dict] = field(default_factory=list)


def _snippet(node: Node | None, limit: int = 400) -> str:
    if node is None:
        return ""
    return (node.html or "")[:limit]


def _same_site(base: str, url: str) -> bool:
    a, b = urlsplit(base).hostname or "", urlsplit(url).hostname or ""
    strip = lambda h: h[4:] if h.startswith("www.") else h  # noqa: E731
    return strip(a) == strip(b)


def parse_page(url: str, html: str) -> PageInfo:
    tree = HTMLParser(html)
    info = PageInfo(url=url, html=html, tree=tree)
    html_node = tree.css_first("html")
    info.lang = html_node.attributes.get("lang") if html_node else None
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        low = href.lower()
        if low.startswith("tel:"):
            info.tel_links.append(href)
            continue
        if low.startswith("mailto:"):
            info.mailto_links.append(href)
            continue
        absu = urljoin(url, href).split("#")[0]
        if re.search(r"(wa\.me/|api\.whatsapp\.com/send|whatsapp://)", low):
            info.whatsapp_links.append(absu)
            continue
        if re.search(r"(facebook\.com|instagram\.com|linkedin\.com/company|twitter\.com|x\.com|tiktok\.com|youtube\.com|pinterest\.)", low):
            info.social_links.append(absu)
        if absu.startswith(("http://", "https://")) and _same_site(url, absu):
            info.internal_links.append(absu)
            text = (a.text(strip=True) or "").lower()
            if re.search(CONTACT_WORDS, text) or re.search(r"/(contact|iletisim|kontakt|contacto|bize-ulasin)", low):
                info.contact_links.append(absu)
    info.images = [urljoin(url, i.attributes.get("src") or "") for i in tree.css("img[src]")
                   if (i.attributes.get("src") or "").strip() and not (i.attributes.get("src") or "").startswith("data:")]
    info.scripts = [urljoin(url, s.attributes.get("src") or "") for s in tree.css("script[src]")]
    info.stylesheets = [urljoin(url, s.attributes.get("href") or "") for s in tree.css("link[rel=stylesheet][href]")]
    for f in tree.css("form"):
        fields = [(i.attributes.get("type") or i.tag or "").lower() for i in f.css("input, textarea, select")]
        names = " ".join((i.attributes.get("name") or "") + " " + (i.attributes.get("placeholder") or "")
                         for i in f.css("input, textarea"))
        info.forms.append({
            "action": f.attributes.get("action") or "", "method": (f.attributes.get("method") or "get").lower(),
            "fields": fields, "has_textarea": "textarea" in fields, "has_email": "email" in fields or "email" in names.lower(),
            "is_search": any(t == "search" for t in fields) or bool(re.search(r"\b(search|q|s)\b", names.lower())) and len(fields) <= 2,
            "is_newsletter": len(fields) <= 3 and "textarea" not in fields and bool(re.search(r"newsletter|bülten|subscribe", (f.html or "").lower())),
        })
    body = tree.body
    info.text = body.text(separator=" ", strip=True)[:200_000] if body else ""
    return info


def _r(key: str, ok: bool | None, page: str, value: dict | None = None, params: dict | None = None,
       evidence: list[EvidenceItem] | None = None, confidence: float = 1.0) -> RuleResult:
    result = UNKNOWN if ok is None else (PASSED if ok else FAILED)
    return RuleResult(key, result, page, value or {}, confidence, params or {}, evidence or [])


def seo_checks(p: PageInfo) -> list[RuleResult]:
    t = p.tree
    out: list[RuleResult] = []
    title_node = t.css_first("head title") or t.css_first("title")
    title = title_node.text(strip=True) if title_node else ""
    out.append(_r("seo.title", 10 <= len(title) <= 70, p.url, {"title": title[:200], "length": len(title)},
                  {"length": len(title)}, [EvidenceItem("html_snippet", "title", p.url, "title", {"html": _snippet(title_node)},
                                                          "static_html")]))
    md = t.css_first('meta[name="description" i]') or t.css_first("meta[name=description]")
    desc = (md.attributes.get("content") or "").strip() if md else ""
    out.append(_r("seo.meta_description", len(desc) >= 50, p.url, {"length": len(desc), "content": desc[:300]},
                  {"length": len(desc)}))
    h1s = t.css("h1")
    out.append(_r("seo.h1", len(h1s) == 1, p.url, {"count": len(h1s), "texts": [h.text(strip=True)[:120] for h in h1s[:5]]},
                  {"count": len(h1s)}))
    levels = [int(h.tag[1]) for h in t.css("h1, h2, h3, h4, h5, h6")]
    skips = [(a, b) for a, b in zip(levels, levels[1:], strict=False) if b - a > 1]
    out.append(_r("seo.heading_hierarchy", (not skips) if levels else None, p.url, {"levels": levels[:50], "skips": skips[:10]}))
    canon = t.css_first("link[rel=canonical]")
    out.append(_r("seo.canonical", bool(canon and canon.attributes.get("href")), p.url,
                  {"href": canon.attributes.get("href") if canon else None}))
    robots_meta = " ".join((m.attributes.get("content") or "").lower() for m in t.css("meta[name=robots], meta[name=googlebot]"))
    out.append(_r("seo.indexable", "noindex" not in robots_meta, p.url, {"robots_meta": robots_meta[:200]}))
    imgs = t.css("img")
    content_imgs = [i for i in imgs if (i.attributes.get("role") or "") != "presentation"]
    with_alt = [i for i in content_imgs if i.attributes.get("alt") is not None]
    ratio = len(with_alt) / len(content_imgs) if content_imgs else None
    out.append(RuleResult("seo.img_alt", NOT_APPLICABLE if ratio is None else (PASSED if ratio >= 0.8 else FAILED), p.url,
                          {"images": len(content_imgs), "with_alt": len(with_alt)},
                          params={"missing": len(content_imgs) - len(with_alt)}))
    og_title = t.css_first('meta[property="og:title"]')
    og_image = t.css_first('meta[property="og:image"]')
    out.append(_r("seo.open_graph", bool(og_title and og_image), p.url,
                  {"og_title": bool(og_title), "og_image": bool(og_image)}))
    ld = t.css('script[type="application/ld+json"]')
    types: list[str] = []
    for s in ld[:10]:
        try:
            data = json.loads(s.text() or "{}")
            items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            for it in items:
                if isinstance(it, dict) and it.get("@type"):
                    types.append(str(it["@type"])[:60])
        except (ValueError, AttributeError):
            continue
    microdata = bool(t.css_first("[itemscope][itemtype]"))
    out.append(_r("seo.structured_data", bool(types) or microdata, p.url, {"jsonld_types": types[:20], "microdata": microdata}))
    out.append(_r("seo.lang", bool(p.lang), p.url, {"lang": p.lang}))
    alternates = [(a.attributes.get("hreflang"), a.attributes.get("href")) for a in t.css("link[rel=alternate][hreflang]")]
    lang_links = [a for a in p.internal_links if re.search(r"/(en|tr|de|nl|fr|es|it|ar|ru)(/|$)", urlsplit(a).path)]
    multilingual = len({re.search(r"/(en|tr|de|nl|fr|es|it|ar|ru)(/|$)", urlsplit(a).path).group(1) for a in lang_links}) >= 2  # type: ignore[union-attr]
    out.append(RuleResult("seo.hreflang", (PASSED if alternates else FAILED) if multilingual else NOT_APPLICABLE, p.url,
                          {"alternates": alternates[:20], "multilingual_detected": multilingual}))
    return out


def structure_checks(p: PageInfo, http_https: bool) -> list[RuleResult]:
    t = p.tree
    low = p.html[:2000].lower()
    has_doctype = low.lstrip().startswith("<!doctype")
    charset = bool(t.css_first("meta[charset]") or t.css_first('meta[http-equiv="Content-Type" i]'))
    title = bool(t.css_first("title"))
    body = t.body is not None and len(p.text) > 0
    missing = [n for n, ok in (("doctype", has_doctype), ("charset", charset), ("title", title), ("body", body)) if not ok]
    out = [_r("tech.html_structure", not missing, p.url, {"missing": missing}, {"missing": ", ".join(missing)})]
    vp = t.css_first("meta[name=viewport]")
    vp_content = (vp.attributes.get("content") or "").lower() if vp else ""
    out.append(_r("tech.viewport_meta", "width=device-width" in vp_content, p.url, {"viewport": vp_content[:200]},
                  evidence=[EvidenceItem("html_snippet", "viewport meta", p.url, "meta[name=viewport]",
                                         {"html": _snippet(vp)}, "static_html")]))
    if http_https:
        insecure = [u for u in p.images + p.scripts + p.stylesheets if u.startswith("http://")]
        out.append(_r("tech.mixed_content", not insecure, p.url, {"insecure": insecure[:20]}, {"count": len(insecure)}))
    else:
        out.append(RuleResult("tech.mixed_content", NOT_APPLICABLE, p.url))
    icon = t.css_first("link[rel~=icon]") or t.css_first("link[rel='shortcut icon']")
    out.append(RuleResult("tech.favicon", PASSED if icon else UNKNOWN, p.url,
                          {"declared": bool(icon), "href": icon.attributes.get("href") if icon else None}))
    return out


def detect_text(patterns: list[str], text: str) -> list[str]:
    hits = []
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            hits.append(m.group(0)[:80])
    return hits


def conversion_checks(pages: list[PageInfo], relevant_features: set[str]) -> list[RuleResult]:
    home = pages[0]
    all_html = "\n".join(p.html[:400_000] for p in pages)
    all_text = " ".join(p.text[:100_000] for p in pages)
    out: list[RuleResult] = []
    contact_links = sorted({u for p in pages for u in p.contact_links})
    out.append(_r("conv.contact_page", bool(contact_links), home.url, {"links": contact_links[:5]}))
    real_forms = [f for p in pages for f in p.forms if not f["is_search"] and not f["is_newsletter"]
                  and (f["has_textarea"] or f["has_email"] or len(f["fields"]) >= 3)]
    embedded = detect_text([r"forms\.gle", r"typeform\.com", r"jotform", r"hsforms", r"wpcf7", r"gform_", r"formspree",
                            r"tally\.so", r"wpforms", r"elementor-form"], all_html)
    out.append(_r("conv.contact_form", bool(real_forms or embedded), home.url,
                  {"forms": len(real_forms), "embedded_providers": embedded}))
    tels = sorted({x for p in pages for x in p.tel_links})
    mails = sorted({x for p in pages for x in p.mailto_links})
    was = sorted({x for p in pages for x in p.whatsapp_links})
    out.append(_r("conv.tel_link", bool(tels), home.url, {"count": len(tels)}))
    out.append(_r("conv.email_link", bool(mails), home.url, {"count": len(mails)}))
    wa_relevant = "whatsapp" in relevant_features
    out.append(RuleResult("conv.whatsapp", (PASSED if was else FAILED) if wa_relevant else (DETECTED if was else NOT_APPLICABLE),
                          home.url, {"count": len(was)}))
    booking = detect_text(BOOKING_PATTERNS, all_html + " " + all_text)
    rel_booking = bool(relevant_features & {"booking", "reservation"})
    out.append(RuleResult("conv.booking", (PASSED if booking else FAILED) if rel_booking else
                          (DETECTED if booking else NOT_APPLICABLE), home.url, {"indicators": booking[:10]},
                          confidence=0.8))
    quote = detect_text(QUOTE_PATTERNS, all_text + " " + all_html[:200_000])
    out.append(RuleResult("conv.quote_form", (PASSED if quote else FAILED) if "quote_form" in relevant_features else
                          (DETECTED if quote else NOT_APPLICABLE), home.url, {"indicators": quote[:10]}, confidence=0.8))
    buttons = [n.text(strip=True)[:60] for n in home.tree.css("a, button") if n.text(strip=True)][:400]
    ctas = [b for b in buttons if any(re.search(p, b, re.IGNORECASE) for p in CTA_PATTERNS)]
    out.append(_r("conv.cta", bool(ctas), home.url, {"examples": ctas[:8]}, confidence=0.7))
    socials = sorted({x for p in pages for x in p.social_links})
    out.append(RuleResult("conv.social_links", DETECTED if socials else NOT_DETECTED, home.url, {"links": socials[:10]}))
    ecommerce = detect_text(ECOMMERCE_PATTERNS, all_html)
    out.append(RuleResult("conv.ecommerce", DETECTED if len(ecommerce) >= 1 else NOT_DETECTED, home.url,
                          {"indicators": ecommerce[:10]}, confidence=0.8 if len(ecommerce) >= 2 else 0.6))
    checkout = detect_text(CHECKOUT_PATTERNS, all_html)
    out.append(RuleResult("conv.checkout", DETECTED if checkout else NOT_DETECTED, home.url, {"indicators": checkout[:10]}))
    return out


def detect_platforms(html: str, headers: dict[str, str]) -> list[dict]:
    found = []
    for key, name, pats in PLATFORMS:
        hits = [p for p in pats if re.search(p, html, re.IGNORECASE)]
        if hits:
            found.append({"key": key, "name": name, "evidence": hits[:3],
                          "confidence": min(1.0, 0.6 + 0.2 * len(hits)), "method": "static_html"})
    powered = headers.get("x-powered-by", "")
    if powered:
        found.append({"key": "server_" + re.sub(r"[^a-z0-9]+", "_", powered.lower())[:30], "name": powered[:60],
                      "evidence": ["x-powered-by header"], "confidence": 0.9, "method": "http_header"})
    if headers.get("x-shopify-stage") or headers.get("x-shopid"):
        found.append({"key": "shopify", "name": "Shopify", "evidence": ["shopify header"], "confidence": 1.0,
                      "method": "http_header"})
    seen, uniq = set(), []
    for f in found:
        if f["key"] not in seen:
            seen.add(f["key"])
            uniq.append(f)
    return uniq


def parked_or_maintenance(p: PageInfo) -> tuple[list[str], list[str]]:
    sample = (p.text[:5000] + " " + p.html[:20000]).lower()
    parked = detect_text(PARKED_PATTERNS, sample)
    # Maintenance indicators count only on thin pages, to avoid matching "coming soon" product teasers.
    maintenance = detect_text(MAINTENANCE_PATTERNS, p.text[:3000]) if len(p.text) < 2500 else []
    return parked, maintenance

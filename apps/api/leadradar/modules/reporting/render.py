"""Server-side rendering of public reports (web and print/PDF share one template)."""

from __future__ import annotations

import base64
from collections.abc import Callable
from functools import lru_cache
from importlib import resources
from typing import Any

from jinja2 import Environment, select_autoescape

LABELS = {
    "en": {
        "audit_date": "Audit date", "updated": "Updated", "version": "Version", "download_pdf": "Download PDF",
        "summary": "Summary", "issues_found": "issues found", "checks_passed": "checks passed",
        "performance": "Performance (lab)", "lab_note": "Lighthouse laboratory measurements under a simulated mobile profile — not real-user field data.",
        "score_performance": "Performance score", "score_accessibility": "Accessibility score",
        "score_best_practices": "Best practices score", "score_seo": "SEO score",
        "mobile": "Mobile usability", "screenshots": "Screenshots", "seo": "Search engine optimization",
        "accessibility": "Accessibility", "tracking": "Measurement & tracking",
        "tracking_note": "Observed client-side at test time. 'Not detected' does not prove that tracking is absent (consent, server-side tagging and regional behaviour can hide tags).",
        "advertising": "Advertising observations", "ads_note": "From official public ad transparency sources. Does not indicate budget or performance.",
        "recommendations": "Recommended improvements", "services": "Recommended services", "notes": "Notes",
        "methodology": "Methodology and limitations", "recommendation": "Recommendation", "passed": "Passed",
        "failed": "Issue", "detected": "Detected", "not_detected": "Not detected", "unknown": "Unknown",
        "active": "Active", "inactive": "Inactive", "password": "Password", "unlock": "View report",
        "password_required": "This report is password protected.", "wrong_password": "Incorrect password.",
        "unavailable": "This report is not available.",
    },
    "tr": {
        "audit_date": "Denetim tarihi", "updated": "Güncelleme", "version": "Sürüm", "download_pdf": "PDF indir",
        "summary": "Özet", "issues_found": "sorun bulundu", "checks_passed": "kontrol başarılı",
        "performance": "Performans (laboratuvar)", "lab_note": "Simüle edilmiş mobil profilde Lighthouse laboratuvar ölçümleri — gerçek kullanıcı saha verisi değildir.",
        "score_performance": "Performans puanı", "score_accessibility": "Erişilebilirlik puanı",
        "score_best_practices": "En iyi uygulamalar puanı", "score_seo": "SEO puanı",
        "mobile": "Mobil kullanılabilirlik", "screenshots": "Ekran görüntüleri", "seo": "Arama motoru optimizasyonu",
        "accessibility": "Erişilebilirlik", "tracking": "Ölçüm ve izleme",
        "tracking_note": "Test anında istemci tarafında gözlemlenmiştir. 'Algılanmadı' izlemenin olmadığını kanıtlamaz (onay, sunucu taraflı etiketleme ve bölgesel davranış etiketleri gizleyebilir).",
        "advertising": "Reklam gözlemleri", "ads_note": "Resmi, herkese açık reklam şeffaflık kaynaklarından alınmıştır. Bütçe veya performans göstermez.",
        "recommendations": "Önerilen iyileştirmeler", "services": "Önerilen hizmetler", "notes": "Notlar",
        "methodology": "Yöntem ve sınırlamalar", "recommendation": "Öneri", "passed": "Başarılı", "failed": "Sorun",
        "detected": "Algılandı", "not_detected": "Algılanmadı", "unknown": "Bilinmiyor", "active": "Aktif",
        "inactive": "Pasif", "password": "Parola", "unlock": "Raporu görüntüle",
        "password_required": "Bu rapor parola korumalıdır.", "wrong_password": "Parola hatalı.",
        "unavailable": "Bu rapor kullanılamıyor.",
    },
}


@lru_cache
def _env() -> Environment:
    return Environment(autoescape=select_autoescape(["html"]), trim_blocks=True, lstrip_blocks=True)


@lru_cache
def _template_text(name: str) -> str:
    return resources.files("leadradar").joinpath(f"templates/{name}").read_text("utf-8")


@lru_cache
def font_data_uri(name: str) -> str:
    data = resources.files("leadradar").joinpath(f"templates/fonts/{name}").read_bytes()
    return "data:font/woff2;base64," + base64.b64encode(data).decode()


def render_report(content: dict[str, Any], *, version: int, lang: str, asset_url: Callable[[str], str],
                  pdf_url: str | None, print_mode: bool, nonce: str) -> str:
    lang = lang if lang in LABELS else "en"
    tpl = _env().from_string(_template_text("report.html"))
    return tpl.render(c=_ns(content), version=version, lang=lang, t=LABELS[lang], asset_url=asset_url,
                      pdf_url=pdf_url, print_mode=print_mode, nonce=nonce, css=_template_text("report.css"),
                      font_sans=font_data_uri("Geist-Variable.woff2"), font_mono=font_data_uri("GeistMono-Variable.woff2"))


def render_message(lang: str, key: str, *, password_form_action: str | None = None, error: str | None = None,
                   nonce: str = "", csrf: str = "") -> str:
    t = LABELS.get(lang, LABELS["en"])
    css = _template_text("report.css")
    form = ""
    if password_form_action:
        err = f'<p class="note">{t[error]}</p>' if error else ""
        form = (f'<form method="post" action="{password_form_action}"><label>{t["password"]}<br>'
                f'<input type="password" name="password" required autocomplete="current-password" '
                f'style="font:inherit;padding:6px 8px;border:1px solid var(--line);border-radius:6px;margin:6px 0 10px;width:260px">'
                f'</label><input type="hidden" name="lang" value="{lang}"><br>'
                f'<button style="font:inherit;padding:6px 12px;border-radius:6px;border:1px solid var(--ink);background:var(--ink);color:var(--paper)">'
                f'{t["unlock"]}</button>{err}</form>')
    return (f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex, nofollow, noarchive, nosnippet"><title>Report</title>'
            f'<style nonce="{nonce}">{css}</style></head><body><main class="report"><p>{t[key]}</p>{form}</main></body></html>')


class _NS(dict):
    """Dict with attribute access for Jinja (missing keys -> None)."""

    def __getattr__(self, item: str) -> Any:
        return self.get(item)


def _ns(v: Any) -> Any:
    if isinstance(v, dict):
        return _NS({k: _ns(x) for k, x in v.items()})
    if isinstance(v, list):
        return [_ns(x) for x in v]
    return v

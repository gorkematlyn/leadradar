"""Regenerate apps/api/leadradar/seeds/data/countries.json (developer tool, not used at runtime).

Source: ISO 3166-1 data and Turkish translations from the ``pycountry`` package (iso-codes
project, LGPL-2.1). Region classification follows the UN M49 geoscheme continents, with
the Americas split into North America (incl. Central America and the Caribbean) and South
America, and Antarctic territories in a separate "antarctica" region.

Usage:  pip install pycountry && python scripts/generate_country_catalog.py
"""

from __future__ import annotations

import gettext
import json
from pathlib import Path

import pycountry

REGIONS = {
    "africa": "DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU YT MA MZ NA NE NG RE RW SH ST SN SC SL SO ZA SS SD TZ TG TN UG EH ZM ZW IO",
    "asia": "AF AM AZ BH BD BT BN KH CN CY GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE",
    "europe": "AX AL AD AT BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM IT JE LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SJ SE CH UA GB XK",
    "north_america": "AI AG AW BS BB BZ BM BQ VG CA KY CR CU CW DM DO SV GL GD GP GT HT HN JM MQ MX MS NI PA PR BL KN LC MF PM VC SX TT TC US VI UM",
    "south_america": "AR BO BR CL CO EC FK GF GY PY PE SR UY VE",
    "oceania": "AS AU CX CC CK FJ PF GU KI MH FM NR NC NZ NU NF MP PW PG PN WS SB TK TO TV VU WF",
    "antarctica": "AQ BV TF HM GS",
}

# Kosovo is not in ISO 3166-1 but is commonly needed; OSM/Geofabrik provide it.
EXTRA = [{"iso2": "XK", "iso3": "XKX", "name_en": "Kosovo", "name_tr": "Kosova"}]


def main() -> None:
    region_of = {code: region for region, codes in REGIONS.items() for code in codes.split()}
    tr = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["tr"])
    out = []
    for c in pycountry.countries:
        name_en = getattr(c, "common_name", None) or c.name
        out.append({
            "iso2": c.alpha_2,
            "iso3": c.alpha_3,
            "name_en": name_en,
            "name_tr": tr.gettext(c.name),
            "region": region_of[c.alpha_2],
            "flag": c.alpha_2.lower(),
        })
    for e in EXTRA:
        out.append({**e, "region": region_of[e["iso2"]], "flag": e["iso2"].lower()})
    missing = [c["iso2"] for c in out if c["iso2"] not in region_of]
    assert not missing, missing
    out.sort(key=lambda c: c["iso2"])
    target = Path(__file__).resolve().parents[1] / "apps/api/leadradar/seeds/data/countries.json"
    target.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} countries to {target}")


if __name__ == "__main__":
    main()

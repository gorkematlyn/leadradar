# OpenStreetMap matching rules

[English](osm-rules.md) · [Türkçe](osm-rules.tr.md)

This guide explains how to define **OSM matching rules** for an industry in **Data Sources → Industries**, and how to find the right OpenStreetMap tags for your target market. It includes a complete worked example for consulting firms.

## 1. Purpose

During Discovery, LeadRadar reads OpenStreetMap (OSM) data and decides, for every place, which industry it belongs to. The decision is made by the matching rules stored with each industry.

- An industry **with** at least one enabled rule is imported from OpenStreetMap.
- An industry **without** rules is shown as **Manual**. It is skipped by OSM imports; companies in that industry are added by CSV import, Quick Audit, the optional Apify integration, or by hand.

Rules are optional. Add them when the businesses you target are likely to be mapped in OpenStreetMap.

## 2. How OpenStreetMap describes a place

Every place in OSM is a set of *tags*: pairs of a **key** and a **value**. For example, a dental practice may carry:

```text
name    = Smile Dental
amenity = dentist
website = https://smile-dental.example
```

A rule is a statement about such tags, for example "the key `amenity` equals `dentist`".

## 3. Fields of the rule form

| Field | Description |
|---|---|
| **Key** | A unique identifier for the rule, for example `consulting_office`. Lower-case letters, digits and `_` only. It cannot be changed after the rule is created. It is *not* an OSM tag. |
| **Classification** | **Confident**: matching places are assigned to the industry directly. **Review candidate**: matching places are imported but flagged, so that their industry can be confirmed. |
| **Description** | A free-text note for your team. |
| **Conditions** | The matching logic, written as JSON (see section 4). |
| **Enabled** | Disabled rules are ignored. |

> The word *key* appears twice in this form. The rule's **Key** is its own identifier. The `key` inside the conditions is the name of the OSM tag that is being checked.

## 4. Writing conditions

Conditions are a JSON object with up to three groups. Each group is a list of conditions.

| Group | Meaning |
|---|---|
| `all` | Every condition must be true (logical AND). |
| `any` | At least one condition must be true (logical OR). |
| `exclude` | No condition may be true. Use it to remove unwanted results. |

Each condition has the following parts:

| Part | Description |
|---|---|
| `key` | The name of the OSM tag to check, for example `office`. |
| `op` | The comparison (see the table below). |
| `value` | The value to compare with. Not used by `exists`. |

| `op` | Meaning | Example |
|---|---|---|
| `eq` | The tag value is exactly equal to `value`. | `{"key": "office", "op": "eq", "value": "consulting"}` |
| `in` | The tag value is one of the listed values. | `{"key": "office", "op": "in", "value": ["tax_advisor", "accountant"]}` |
| `exists` | The tag is present, whatever its value. | `{"key": "name", "op": "exists"}` |
| `regex` | The tag value contains a match for a pattern. Not case-sensitive; the pattern may match anywhere in the value. Use `\|` to separate alternatives. | `{"key": "name", "op": "regex", "value": "consult\|advis"}` |

If a place does not carry the tag at all, the condition is false.

## 5. Recommendations

1. **Start from a structural tag.** Every rule should contain at least one condition on an OSM tag other than `name` (for example `office`, `amenity`, `shop`). Rules that rely on `name` alone are not supported, because the import first filters places by tag key.
2. **Place the structural tag before `name`** in the `all` list.
3. **Use `in` for several values of the same tag.** Avoid `any` lists that mix different tag keys: only the first key of an `any` list is used to pre-select places.
4. **Require a name** with `{"key": "name", "op": "exists"}`. Unnamed places are of little use for outreach.
5. **Use `exclude` for chains and unwanted types.** `{"key": "brand:wikidata", "op": "exists"}` removes most branded chains.
6. **Prefer Review candidate for name-based rules.** Names are ambiguous; a human check keeps the data reliable.
7. **Test before importing.** See section 7.

## 6. Worked example: consulting firms

Goal: find businesses that offer advisory services of any kind, such as management, education, visa, tax or financial consulting. OSM does not have one tag for all of these, so three complementary rules are used.

**Rule 1 – Tagged consulting offices** (Confident, key `consulting_office`)

```json
{
  "all": [
    {"key": "office", "op": "eq", "value": "consulting"},
    {"key": "name", "op": "exists"}
  ]
}
```

**Rule 2 – Financial, tax and legal advisers** (Confident, key `finance_tax_advisors`)

```json
{
  "all": [
    {"key": "office", "op": "in", "value": ["financial_advisor", "tax_advisor", "accountant", "lawyer"]},
    {"key": "name", "op": "exists"}
  ]
}
```

**Rule 3 – Advisory businesses identified by name** (Review candidate, key `name_consulting`)

```json
{
  "all": [
    {"key": "office", "op": "in", "value": ["company", "travel_agent", "educational_institution", "yes"]},
    {"key": "name", "op": "regex", "value": "danışman|danisman|müşavir|musavir|consult|advis|visa|vize"}
  ],
  "exclude": [
    {"key": "brand:wikidata", "op": "exists"}
  ]
}
```

Education and visa advisers rarely have a dedicated tag. They are usually mapped as a general office, a travel agency or an educational institution, so they can only be recognised by their name. Adapt the words in the pattern to the languages of your target countries.

## 7. Testing a rule

On the **Data Sources** page, use the **Test tags** panel. Enter the tags of a sample place, one `key=value` per line:

```text
name=Aksoy Danışmanlık
office=company
```

The panel lists the industries and rules that match. Nothing is saved.

## 8. Finding the right tags

| Resource | Use |
|---|---|
| [openstreetmap.org](https://www.openstreetmap.org) | Locate a known business on the map and click the **Query features** button (arrow with a question mark). It shows the exact tags of the place. |
| [TagInfo](https://taginfo.openstreetmap.org) | Look up a key or key=value pair, for example `office=consulting`, to see how often it is used and which other tags appear with it. A small count means the tag is rarely used. |
| [OSM Wiki – Map features](https://wiki.openstreetmap.org/wiki/Map_features) | The official catalogue of tags, grouped by theme. |
| [OSM Wiki – Key:office](https://wiki.openstreetmap.org/wiki/Key:office) | All values of the `office` key, which covers most professional services. |
| [Overpass Turbo](https://overpass-turbo.eu) | Run a query for a tag in a chosen area and see the results on a map. |
| [Geofabrik downloads](https://download.geofabrik.de) | The data extracts that LeadRadar imports. |

Tag usage changes over time. Always confirm a tag on TagInfo or the wiki before building a rule on it.

## 9. Coverage and alternatives

OpenStreetMap is maintained by volunteers. Offices of professional services are mapped far less completely than shops or restaurants, and a missing website or phone number does not mean that the business has none. Expect OSM rules to find a part of the market only.

For a broader list, combine OSM rules with:

- **CSV import** of a purchased or self-compiled list,
- **Quick Audit** of individual websites,
- the optional **Apify** integration (for example a maps scraper), subject to its terms of use and your budget limits.

## 10. Common mistakes

| Symptom | Likely cause |
|---|---|
| The rule never matches. | Only `name` is used, or the tag value is spelled differently in OSM. Check it with the Test tags panel and TagInfo. |
| The rule matches too much. | The pattern is too short (for example `ad`). Use longer words or add an `exclude` group. |
| The form reports invalid conditions. | The JSON is malformed (missing comma or quotation mark), or an operator other than `eq`, `in`, `exists`, `regex` is used. |
| A match is expected but the place is missing after an import. | The place has no `name`, the country or region was not imported yet, or the extract was skipped because it had not changed (use *Re-download even if unchanged*). |

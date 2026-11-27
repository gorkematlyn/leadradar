# Changelog

## 0.2.0

### Fixed
- **Geofabrik downloads failed with HTTP 302/307.** Downloads now follow Geofabrik's mirror redirects; every hop is still checked by the egress policy.
- **Imports stayed "queued" forever.** Regions of a country run one after another; a failed or cancelled region no longer blocks the regions after it.
- **Import status after cancelling.** Cancelling jobs (one by one or per country) now updates the import runs and the country status, so Discovery no longer shows "failed" or "queued" for imports that were cancelled.
- **Scoring versions increased without changes.** Saving identical values no longer creates a new profile or rule version. Profiles whose values still equal the defaults are reset to version 1 by migration `0002`.
- **Notifications** open the related job, close the menu, and no longer appear twice for one failed import.
- Ad provider links edited by the administrator are no longer overwritten on restart.

### Added
- Discovery: explanation of "Enabled" versus the selection checkbox; enabling a country selects it automatically.
- Discovery and Overview: import progress per country ("3/10 regions", downloaded MB), grouped by continent, with pause, resume and cancel for a whole country.
- Clearing records: import history, finished background jobs (all or one at a time), notifications and Overview warnings, each with a confirmation.
- Saved selections: unique names with an overwrite prompt, rename, update with the current selection, delete.
- Tags have an English and a Turkish name and description; filters use the tag ID, so they work in both languages.
- Countries, industries and tags are sorted alphabetically in the active language.
- Data Sources: long OSM rules wrap inside the page; help texts for OSM rules (what they do, when they are optional), Apify Actor fields and provider settings; pencil button to edit each provider's official and search links.
- Help icons (circled ?) with short explanations on technical settings across the app; translated job stages and statuses ("Retries exhausted" instead of "Dead letter").
- Jobs page: page X of Y, record range and first/last page buttons.

### Upgrade notes
- Migration `0002` runs automatically when the `api` service starts. It renames the tag columns, converts saved filters from tag names to tag IDs and resets unchanged scoring profiles to version 1.

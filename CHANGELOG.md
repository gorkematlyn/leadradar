# Changelog

## 0.3.0

### Added
- **Company trash.** Companies can be deleted one by one or in bulk; they move to a trash for 30 days (restore or delete permanently, empty the trash) and are then purged automatically. Trashed companies are hidden everywhere, and their public report links stop working. Do Not Contact entries always survive.
- **Editable CRM statuses** (Settings → CRM statuses): rename in both languages, reorder, show or hide in the pipeline, mark as closing, add and delete. Companies in a deleted status are moved to a status you choose. *New*, *Do not contact* and *Archived* are system statuses (rename only).
- **CRM pipeline table**: status, opportunities sorted by score, lead score, number of reports (hover: latest five, newest first, with "+N more") and number of ads from the latest research (hover: per-platform breakdown). Clicking a company opens a summary dialog with editable status and follow-up. The Kanban/Table choice is remembered.
- **Discovery**: the start button is now *Start discovery*, followed by a confirmation that explains what happens next, with a link to Companies. New switch *Add businesses without a website* (off by default: places without a website are skipped).
- **Dynamic filters**: company filters only offer countries, regions, industries, statuses, tags and platforms that occur in the data, with counts.
- Website and CRM status can be changed from the company header.

### Changed
- Tables fit the screen: toolbar, column headers and pagination stay in place, only the rows scroll, and the horizontal scrollbar is always visible.
- The company list keeps its filter, sorting and page in the address bar, so returning from a company page restores it.

### Fixed
- Companies without a website showed "Not verified" instead of "Website not found" (existing records are corrected by migration `0003`).
- A vertical scrollbar appeared next to the company tabs; the Turkish notification header overflowed.

## 0.2.2

### Documentation
- New guide to OSM matching rules in English and Turkish ([docs/osm-rules.md](docs/osm-rules.md), [docs/osm-rules.tr.md](docs/osm-rules.tr.md)): field reference, writing conditions, a worked example for consulting firms, testing, and links to OpenStreetMap, TagInfo, the OSM wiki and Overpass Turbo. A test keeps the JSON examples valid.

## 0.2.1

### Fixed
- **Every Geofabrik import failed.** Two causes:
  - The built-in egress proxy closed every connection after 60 MB (a limit meant for website audits), so larger extracts never finished downloading. Geofabrik downloads now use a separate proxy with the same destination checks but no size cap.
  - The discovery worker image was missing the system library `libexpat1`, so the OSM parser could not start (`ImportError: libexpat.so.1`). The image now installs it, and the build fails if the parser cannot be imported.
- A dropped download connection now resumes from the partial file within the same attempt, instead of using up a retry.
- **Import progress disappeared after "Clear finished jobs".** A country's planning job is finished while its regions are still running; such jobs are no longer deleted. Progress is also rebuilt from the region jobs if the planning job record is already gone.

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

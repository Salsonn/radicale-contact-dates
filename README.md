# radicale-contact-dates

Generate one read-only **"Contact dates" calendar per addressbook** in
[Radicale](https://radicale.org/) from the dates stored on your CardDAV
contacts — birthdays, anniversaries, and any custom labeled date. Stdlib-only
Python, no dependencies.

It reads the addressbooks in your Radicale `multifilesystem` storage, derives a
single combined calendar for each one (named `<collection>-auto-contact-dates`),
and keeps it in sync — adding, updating, and removing events as your contacts
change. The generated calendars are served read-only, so they show up in any
CalDAV client (phone, desktop, web) without anyone being able to edit them.

All date types share **one** calendar per addressbook; they are differentiated
by their `CATEGORIES` value (Birthday / Anniversary / your custom label) and an
emoji in the title (🎂 / 💍 / 📅).

---

## What it does

For every contact, each enabled **date type** emits, per occurrence, **one
all-day VEVENT per reminder** — the date itself plus "look-ahead" events on the
days before. Each event's `SUMMARY` (and `DESCRIPTION`) holds its own text and it
carries a popup `VALARM` at its time, so the right text shows on **every** client
— including Android/Apple, which ignore `VALARM` `DESCRIPTION` and only display
the event `SUMMARY`. Below are two of the three default events for `Casey
Example` (born 1980-04-10): the day-of and the 7-day look-ahead.

### Birthday (🎂) — day-of, on 10 April

```ics
BEGIN:VEVENT
UID:auto-birthday-casey-example-2026-r0@radicale
DTSTART;VALUE=DATE:20260410
DTEND;VALUE=DATE:20260411
SUMMARY:🎂 Casey Example turns 46
DESCRIPTION:🎂 Casey Example turns 46
TRANSP:TRANSPARENT
CATEGORIES:Birthday
X-AUTO-CONTACT-DATE-SOURCE:casey-example
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:PT11H30M
DESCRIPTION:🎂 Casey Example turns 46
END:VALARM
END:VEVENT
```

### Birthday (🎂) — 7-day look-ahead, on 3 April

```ics
BEGIN:VEVENT
UID:auto-birthday-casey-example-2026-r1@radicale
DTSTART;VALUE=DATE:20260403
DTEND;VALUE=DATE:20260404
SUMMARY:🎂 Casey Example turns 46 on 10 April
DESCRIPTION:🎂 Casey Example turns 46 on 10 April
TRANSP:TRANSPARENT
CATEGORIES:Birthday
X-AUTO-CONTACT-DATE-SOURCE:casey-example
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:PT11H30M
DESCRIPTION:🎂 Casey Example turns 46 on 10 April
END:VALARM
END:VEVENT
```

(A 1-day look-ahead on 9 April — "🎂 Casey Example turns 46 tomorrow" — is
generated too. The `anniversary` defaults are the same shape with `💍` and
`{count_english}`, e.g. `💍 Casey Example's 25th anniversary`.)

A source whose **year is unknown** (e.g. Apple's `X-APPLE-OMIT-YEAR`, the `1604`
sentinel, or vCard 4.0 `--MM-DD`) instead gets **perpetual** events with
`RRULE:FREQ=YEARLY`, using each reminder's `template_unknown`.

---

## How it works

```
discover addressbooks  ->  build desired events  ->  reconcile  ->  write files
   (<user>/<coll>)        (per contact, per type)   (diff vs disk)  (atomic, as uid)
```

1. **Discover** every `<user>/<collection>` addressbook under the storage root
   (skipping the `*-auto-contact-dates` outputs).
2. **Desired set** — for each contact, and for each enabled `date_type`, compute
   the events it should have in the window (see `future_days` / `past_days`).
   Everything for one addressbook lands in its single combined calendar.
3. **Reconcile** the desired set against what is already on disk: create new
   files, update changed ones, delete stale ones. `DTSTAMP` is ignored in the
   comparison, so unchanged events are never needlessly rewritten (idempotent).
4. **Write** the changes atomically into `<collection>-auto-contact-dates/`.

### How read-only works

There are two halves, and they are independent:

- **Clients see the calendars as read-only** via a Radicale `from_file` rights
  rule that grants only `r` on any `*-auto-contact-dates` collection. See
  [`examples/rights.snippet`](examples/rights.snippet). Because Radicale matches
  rights **first-match-wins**, this rule must be placed **before** any broader
  read-write rule.

- **The generator still writes them** because it does **not** go through the
  CalDAV API or the rights layer at all. It writes the `.ics` files **directly
  on the filesystem, as the Radicale storage uid** (the user that owns the
  collection files). That bypasses rights entirely.

Radicale's `multifilesystem` storage discovers filesystem changes **live**, so
once the files are written the new events appear immediately — **no Radicale
restart and no container restart needed**.

---

## Requirements

- **Radicale 3.x** with `multifilesystem` storage (the read-only trick,
  `.Radicale.props`, and direct filesystem writes are specific to it).
- **Python 3.8+**, standard library only — no third-party packages.

A generic CalDAV-API write mode is out of scope; this tool targets the Radicale
filesystem layout directly.

---

## Parsing

For each contact, dates are collected from three sources:

- **`BDAY`** — the standard vCard birthday property.
- **`ANNIVERSARY`** (and `X-ANNIVERSARY`) — the standard vCard anniversary
  property, decoded with label `Anniversary`.
- **Apple labeled dates** — `itemN.X-ABDATE` paired with `itemN.X-ABLABEL` by
  their shared `itemN` prefix. Any property parameters (e.g. `;TYPE=pref`) are
  stripped from the date. Apple-encoded labels `_$!<Anniversary>!$_` are decoded
  to `Anniversary`; plain labels (e.g. `Graduation`, added by Android/DAVx5)
  pass through unchanged. An `X-ABDATE` with no matching `X-ABLABEL` has label
  `None`.

All sources accept the same date formats: ISO (`1980-04-10`), basic
(`19800410`), vCard 4.0 (`--04-10` / `--0410`), an optional time suffix
(`...T00:00:00`), and the `X-APPLE-OMIT-YEAR` / `1604` year sentinels (which mark
the year as unknown → a perpetual event).

A contact whose `NOTE` contains the blacklist marker (`#NB` by default, matched
whole-word, case-insensitive) is **skipped entirely** — none of its date types
are generated, and any previously generated events for it are removed on the next
sync.

---

## Configuration

Pass a JSON config with `--config`. Anything you omit falls back to the built-in
defaults (which are English) via a deep-merge, so a partial config only overrides
the keys you set. Two ready-to-edit examples are provided:

- [`examples/config.en.json`](examples/config.en.json) — English; mirrors the
  defaults **exactly**.
- [`examples/config.nl.json`](examples/config.nl.json) — a Dutch localization
  that reuses the **same** placeholder keys and only changes the wording,
  `month_names`, `displayname_prefix`, and each type's `category`. (Note: Dutch
  ordinals are rendered with `{count}` + `e` rather than the English `{ordinal}`,
  e.g. `{count}e jubileum`.)

### Global reference

| Key | Default | Meaning |
|---|---|---|
| `future_days` | `730` | How far ahead (days) to materialize dated events. |
| `past_days` | `365` | How far back (days) to keep dated events. |
| `blacklist_note_marker` | `#NB` | Marker token; a contact whose `NOTE` contains it is skipped. |
| `month_names` | English 1..12 | 12-entry list (index 0 is `""`) used by the `{date}` placeholder. |
| `date_format` | `{day} {month}` | `str.format` template that builds the `{date}` placeholder — controls **order** (see below). |
| `suffix` | `-auto-contact-dates` | Appended to each addressbook name to form the single combined calendar. |
| `displayname_prefix` | `Contact dates` | Prefix for the generated calendar's display name, e.g. `Contact dates (Alice)`. |
| `prodid` | `-//radicale-contact-dates//EN` | `PRODID` written into each VCALENDAR. |
| `collections` | wildcard map | Which addressbooks to process (see below). |
| `date_types` | birthday + anniversary | Per-type definitions (see below). |

### `date_types`

`date_types` is a map of type name → definition. Three are shipped: `birthday`
and `anniversary` enabled, plus a disabled catch-all `other_dates`. Each
definition supports:

| Field | Used by | Meaning |
|---|---|---|
| `enabled` | all | Whether this type is generated. |
| `source` | `birthday` | `"BDAY"` reads the `BDAY` property directly. Other types match labeled dates via `apple_label`; the standard `ANNIVERSARY` property is folded in automatically (label `Anniversary`). |
| `apple_label` | `anniversary` | Decoded `X-ABLABEL` to match (case-insensitive), e.g. `Anniversary`. |
| `match` | `other_dates` | `x-abdate-any` claims every labeled date **not** already claimed by a more specific enabled type (first-match-wins). |
| `category` | all | Value of the `CATEGORIES` property (Birthday / Anniversary / Important date). |
| `reminders` | all | What to generate — a list of reminders (see below). **At least one `type: "event"` is required.** |

The catch-all `other_dates` is what surfaces custom labels (its `{label}`
placeholder renders the decoded `X-ABLABEL`); enable it if you want events for
dates like `Graduation`.

#### `reminders`

Each `date_type` has a flat `reminders` list. Each reminder is **one** of two
kinds, set by `type`:

- **`type: "event"`** → an all-day `VEVENT` on *(occurrence − `days_before`)*.
  Its `SUMMARY` **and** `DESCRIPTION` are the rendered `template`, and it carries
  its own popup `VALARM` at `at`. Shows the right text on **every** client
  (it's a real `SUMMARY`).
- **`type: "alarm"`** → just a `VALARM` appended to the **day-of event** (the
  `event` reminder whose `days_before` is closest to 0); trigger from its
  `days_before`+`at`, `DESCRIPTION` = the rendered template. No calendar entry —
  cheaper, but clients that ignore `VALARM` `DESCRIPTION` show the host event's
  `SUMMARY` instead.

| Field | Meaning |
|---|---|
| `days_before` | Days before the date (`0` = the date itself). |
| `at` | `HH:MM` local time of the popup. |
| `type` | `"event"` or `"alarm"`. |
| `template` | Text (a `str.format` string) when the year is **known**. |
| `template_unknown` | Text when the year is **unknown** (perpetual). |

```json
"reminders": [
  {"days_before": 0, "at": "11:30", "type": "event",
   "template": "🎂 {name} turns {count}",
   "template_unknown": "🎂 {name}'s birthday"},
  {"days_before": 7, "at": "11:30", "type": "event",
   "template": "🎂 {name} turns {count} on {date}",
   "template_unknown": "🎂 {name}'s birthday on {date}"},
  {"days_before": 1, "at": "11:30", "type": "event",
   "template": "🎂 {name} turns {count} tomorrow",
   "template_unknown": "🎂 {name}'s birthday tomorrow"}
]
```

The shipped defaults use `type: "event"` for **all** reminders, so the text is
correct on every client (notably Android/Apple, which ignore `VALARM`
`DESCRIPTION`). Switch a reminder to `type: "alarm"` only if you want a cheap
popup and accept that those clients show the host event's title instead.

Behaviour:

- **Validation:** an enabled type with no `type: "event"` reminder is an error
  (alarms need an event to host them).
- **Perpetual** (year unknown) → the event recurs yearly (`RRULE:FREQ=YEARLY`)
  and uses `template_unknown`.
- **Prune:** an `event` reminder with `days_before > 0` is dropped once its day
  has passed; the day-of event (and its hosted alarms) stay per `past_days`.
- One file per `event` reminder per occurrence:
  `auto-<type>-<uid>[-<year>]-r<i>.ics` (`i` = index in `reminders`). Alarms
  live inside their host event's file.

#### Template placeholders

Each `template` / `template_unknown` is a Python `str.format` string and may use:

| Placeholder | Example | Notes |
|---|---|---|
| `{name}` | `Casey Example` | The contact's `FN`. |
| `{count}` | `46` | Years since the base date — the age turned / Nth occurrence (empty when the year is unknown). |
| `{age}` | `46` | Alias of `{count}`. |
| `{years}` | `46` | Alias of `{count}`. |
| `{ordinal}` | `25th` | English ordinal of `{count}`. For other languages use `{count}` + your own suffix. |
| `{count_english}` | `25th` | Explicit alias of `{ordinal}`. |
| `{label}` | `Graduation` | The decoded date label (`X-ABLABEL`), mainly for `other_dates`. |
| `{day}` | `10` | Day of month (numeric). |
| `{date}` | `10 April` | The date itself (see `date_format`). |
| `{year}` | `2026` | Occurrence year (empty when unknown). |

Use `template_unknown` to phrase the year-unknown case differently (e.g.
`🎂 {name}'s birthday` vs `🎂 {name} turns {count}`).

#### `date_format`

The `{date}` placeholder is assembled from the global `date_format` (a
`str.format` string, default `"{day} {month}"`). This controls the **order**,
which `month_names` alone cannot. Placeholders available inside `date_format`:

| Placeholder | Example | Notes |
|---|---|---|
| `{day}` | `10` | Day of month (numeric). |
| `{month}` | `April` | Month name from `month_names`. |
| `{month_num}` | `4` | Month (numeric). |
| `{year}` | `2026` | Occurrence year (empty for perpetual events). |
| `{day_english}` | `10th` | Day with an **English** ordinal suffix — a convenience, not localized. |

Examples: `"{day} {month}"` → `10 April` (default, NL/UK); `"{month} {day}"` →
`April 10` (US); `"{month} {day_english}"` → `April 10th`; `"{day}. {month}"` →
`10. April` (DE).

#### `collections`

A map of `fnmatch` wildcard patterns to settings. The **first** matching pattern
wins per collection; a collection with no match (or `enabled: false`) is skipped.

```json
"collections": {
  "*/contacts": {"enabled": true},
  "*/archived-contacts": {"enabled": false}
}
```

### Skipping a contact (`#NB` in NOTE)

To exclude a single contact, add the blacklist marker (default `#NB`) anywhere
in their vCard `NOTE`. The match is whole-word and case-insensitive. On the next
sync, **all** of that contact's generated events (every date type) are removed.

```
NOTE:Work contact — no dates wanted #NB
```

---

## Behavior notes

- **Idempotent reconcile.** Re-running with no contact changes writes nothing;
  the on-disk events are diffed (ignoring `DTSTAMP`) and left untouched.
- **Dated vs perpetual.** Sources with a known year get a **dated** event per
  occurrence in the window (using `template`). Sources without a year get a
  **perpetual** `RRULE:FREQ=YEARLY` event (using `template_unknown`).
- **`{count}` = years since the base date.** For a birthday it is the age turned
  (`turns 46`); for an anniversary it is the Nth (`25th anniversary`) — the same
  `occurrence_year − base_year` logic for every type.
- **Reminders: events vs alarms.** Each reminder is either an `event` (an
  all-day `VEVENT` shown in the calendar — correct text on every client) or an
  `alarm` (a `VALARM` hosted on the day-of event). At least one `event` is
  required. Spent advance events are pruned once their day passes; the day-of
  event stays. See [`reminders`](#reminders).
- **Feb 29.** Leap-day dates fall back to **Feb 28** in non-leap years.
- **Window.** Dated events exist only within `[today - past_days,
  today + future_days]`; older/newer ones are pruned as the window slides.
- **Groups & non-contacts.** Contacts with no parseable date are ignored — this
  includes group vCards (`X-ADDRESSBOOKSERVER-KIND:group`), which carry none.

---

## Deployment

The tool is meant to be run on a schedule (typically once a day) as the Radicale
storage uid, against the live collection root. A complete wrapper with logging
and exit-code propagation is in
[`examples/run-contact-dates.sh`](examples/run-contact-dates.sh).

The core invocation (adjust the uid, container name, and paths to your setup):

```sh
docker exec -u <storage-uid> <container> \
  python3 /plugins/contact_dates.py \
  --config /plugins/contact-dates.config.json \
  --root /data/collections/collection-root
```

Useful flags: `--dry-run` (report changes without writing), `--verbose` (list
each created/updated/deleted file), and `--collection <user>/<name>` (limit to
one addressbook).

### Schedule it

- **cron** (run as a user that can `docker exec`):

  ```cron
  0 3 * * * /path/to/run-contact-dates.sh
  ```

- **Synology Task Scheduler:** create a *User-defined script* task, run daily,
  with the command pointing at your copy of `run-contact-dates.sh`.

No restart is needed after a run — Radicale serves the new files live.

### Make the calendars read-only

Add the block from [`examples/rights.snippet`](examples/rights.snippet) to your
Radicale `from_file` rights file, **before** your read-write rules:

```ini
[auto-contact-dates-readonly]
user: .+
collection: .*-auto-contact-dates(/.*)?
permissions: r
```

---

## License

MIT — see [LICENSE](LICENSE).

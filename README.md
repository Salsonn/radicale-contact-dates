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

For every contact, each enabled **date type** emits one all-day VEVENT per
occurrence with a few reminder `VALARM`s. Below are two real generated events for
a contact (`Casey Example`) born 1980-04-10 with a wedding anniversary on
2001-04-10.

### Birthday (🎂)

```ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//radicale-contact-dates//EN
BEGIN:VEVENT
UID:auto-birthday-casey-example-2026@radicale
DTSTAMP:20260531T200626Z
DTSTART;VALUE=DATE:20260410
DTEND;VALUE=DATE:20260411
SUMMARY:🎂 Casey Example turns 46
TRANSP:TRANSPARENT
CATEGORIES:Birthday
X-AUTO-CONTACT-DATE-SOURCE:casey-example
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-P6DT12H30M
DESCRIPTION:🎂 Casey Example turns 46 on 10 April
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT12H30M
DESCRIPTION:🎂 Casey Example turns 46 on 10 April
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:PT11H30M
DESCRIPTION:🎂 Casey Example turns 46 today
END:VALARM
END:VEVENT
END:VCALENDAR
```

### Anniversary (💍)

```ics
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//radicale-contact-dates//EN
BEGIN:VEVENT
UID:auto-anniversary-casey-example-2026@radicale
DTSTAMP:20260531T200626Z
DTSTART;VALUE=DATE:20260410
DTEND;VALUE=DATE:20260411
SUMMARY:💍 Casey Example — 25th anniversary
TRANSP:TRANSPARENT
CATEGORIES:Anniversary
X-AUTO-CONTACT-DATE-SOURCE:casey-example
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-P6DT12H30M
DESCRIPTION:💍 Casey Example's 25th anniversary on 10 April
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:-PT12H30M
DESCRIPTION:💍 Casey Example's 25th anniversary on 10 April
END:VALARM
BEGIN:VALARM
ACTION:DISPLAY
TRIGGER:PT11H30M
DESCRIPTION:💍 Casey Example's 25th anniversary today
END:VALARM
END:VEVENT
END:VCALENDAR
```

A source whose **year is unknown** (e.g. Apple's `X-APPLE-OMIT-YEAR`, the `1604`
sentinel, or vCard 4.0 `--MM-DD`) instead gets a single **perpetual** event with
`RRULE:FREQ=YEARLY` and no count in the text.

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
| `alarms` | all | List of `{days_before, at}` reminders (see below). |
| `templates` | all | Text templates for the summary and alarms (see below). |

The catch-all `other_dates` is what surfaces custom labels (its `{label}`
placeholder renders the decoded `X-ABLABEL`); enable it if you want events for
dates like `Graduation`.

#### `alarms`

A list of reminders, each `{"days_before": N, "at": "HH:MM"}`. `days_before: 0`
means a reminder on the day itself; `> 0` means N days before. The default for
every shipped type is seven days before, one day before, and on the day — all at
11:30.

Each alarm may additionally set:

| Field | Default | Meaning |
|---|---|---|
| `type` | `"alarm"` | `"alarm"` → a `VALARM` on the date event (as before). `"event"` → a **separate timed reminder `VEVENT`** at the reminder moment. |
| `duration` | `"PT1M"` | ISO 8601 length of the reminder event (`type: "event"` only). `"PT0S"` = `DTSTART == DTEND`. |

**Why `type: "event"`?** Many clients (e.g. Apple, Google) ignore a `VALARM`'s
`DESCRIPTION` and show the event's `SUMMARY` in the notification instead — so the
per-lead context (`… on 10 April` vs `… today`) is lost. A reminder *event*
carries that text in its own `SUMMARY`, so it shows correctly everywhere. The
date event keeps `VALARM`s only for `type: "alarm"` entries (so no double
notification); each reminder event fires via its own `TRIGGER:PT0S` alarm. It
uses a floating-local time (no time zone) and, for year-unknown contacts, recurs
yearly. Files are named `auto-<type>-<uid>[-<year>]-r<i>.ics`.

#### `templates` and placeholders

Templates are fully user-controlled; only the **placeholder keys** are fixed.
Each template is a Python `str.format` string and may use any of:

| Placeholder | Example | Notes |
|---|---|---|
| `{name}` | `Casey Example` | The contact's `FN`. |
| `{count}` | `46` | Years since the base date — the age turned / Nth occurrence (empty for perpetual / unknown-year events). |
| `{age}` | `46` | Alias of `{count}`. |
| `{years}` | `46` | Alias of `{count}`. |
| `{ordinal}` | `25th` | English ordinal of `{count}`. Renders English suffixes; for other languages use `{count}` + your own suffix. |
| `{count_english}` | `25th` | Explicit alias of `{ordinal}`. |
| `{label}` | `Graduation` | The decoded date label (`X-ABLABEL`), mainly for `other_dates`. |
| `{day}` | `10` | Day of month (numeric). |
| `{date}` | `10 April` | Day + localized month name (from `month_names`). |
| `{year}` | `2026` | Occurrence year (empty for perpetual events). |

Each type has six template keys. `*_with_count` is used when the base year is
known; `*_no_count` when it is unknown (perpetual):

| Template key | Default (birthday) | Used for |
|---|---|---|
| `summary_with_count` | `🎂 {name} turns {count}` | `SUMMARY`, year known. |
| `summary_no_count` | `🎂 {name}'s birthday` | `SUMMARY`, year unknown. |
| `alarm_before_with_count` | `🎂 {name} turns {count} on {date}` | Reminder before the day, year known. |
| `alarm_before_no_count` | `🎂 {name}'s birthday on {date}` | Reminder before the day, year unknown. |
| `alarm_day_with_count` | `🎂 {name} turns {count} today` | Reminder on the day, year known. |
| `alarm_day_no_count` | `🎂 {name}'s birthday today` | Reminder on the day, year unknown. |

The `anniversary` defaults use `{ordinal}` (`💍 {name} — {ordinal} anniversary`),
and `other_dates` uses `{label}` (`📅 {name} — {label}`).

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
- **Dated vs perpetual.** Sources with a known year get one **dated** event per
  occurrence in the window, each carrying its count. Sources without a year get
  a single **perpetual** `RRULE:FREQ=YEARLY` event with no count.
- **`{count}` = years since the base date.** For a birthday it is the age turned
  (`turns 46`); for an anniversary it is the Nth (`25th anniversary`) — the same
  `occurrence_year − base_year` logic for every type.
- **Reminder events (opt-in).** An alarm with `type: "event"` becomes a separate
  timed `VEVENT` whose `SUMMARY` carries the reminder text, so clients that
  ignore `VALARM` descriptions still notify correctly. See `alarms` above.
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

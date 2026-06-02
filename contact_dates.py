#!/usr/bin/env python3
"""radicale-contact-dates: read-only contact-date calendars from vCards.

Generate one combined "Contact dates" calendar per addressbook, populated from
config-driven ``date_types`` (birthday, anniversary, optional catch-all),
parsing ``BDAY``, ``ANNIVERSARY`` and Apple ``X-ABDATE``/``X-ABLABEL`` dates.

Stdlib-only. Pure functions (parsing, dates, ICS building, reconcile) are kept
separate from the filesystem/orchestration layer so they can be unit-tested.

See README.md for configuration and deployment.
"""
from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import re
import shutil
import tempfile

PRODID = "-//radicale-contact-dates//EN"
DEFAULT_MONTHS = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
DEFAULT_DATE_FORMAT = "{day} {month}"
DEFAULT_REMINDER_DURATION = "PT1M"

# Shared alarm schedule reused by every shipped date_type.
_DEFAULT_ALARMS = [
    {"days_before": 7, "at": "11:30"},
    {"days_before": 1, "at": "11:30"},
    {"days_before": 0, "at": "11:30"},
]


# --- vCard parsing --------------------------------------------------------

_FOLD_RE = re.compile(r"\r?\n[ \t]")
_ITEM_RE = re.compile(r"^(item\d+)\.", re.IGNORECASE)
_APPLE_LABEL_RE = re.compile(r"^_\$!<(.*)>!\$_$")


def _decode_apple_label(value):
    """Decode Apple labels: '_$!<X>!$_' -> 'X'; otherwise pass through."""
    m = _APPLE_LABEL_RE.match(value)
    return m.group(1) if m else value


def parse_vcard(text):
    """Raw vCard text -> dict.

    Keys: {uid, fn, bday, note, categories, labeled_dates}. Unfold + CRLF.
    ``labeled_dates`` is a list of {"date": <raw>, "label": <decoded or None>}
    built from Apple ``itemN.X-ABDATE``/``itemN.X-ABLABEL`` pairs (keyed by
    item id) plus standard ``ANNIVERSARY``/``X-ANNIVERSARY`` (label
    "Anniversary").
    """
    text = _FOLD_RE.sub("", text)
    out = {"uid": None, "fn": None, "bday": None, "note": None,
           "categories": [], "labeled_dates": []}
    # item id -> raw date value (preserving first-seen order)
    abdates = {}
    abdate_order = []
    # item id -> decoded label
    ablabels = {}
    anniversaries = []
    for raw in text.split("\n"):
        line = raw.rstrip("\r")
        if not line or ":" not in line:
            continue
        prop = line.split(":", 1)[0]
        item_m = _ITEM_RE.match(prop)
        item_id = item_m.group(1).lower() if item_m else ""
        # Property name without item prefix and without params, upper-cased.
        bare = prop[item_m.end():] if item_m else prop
        name = bare.split(";", 1)[0].upper()
        value = line.split(":", 1)[1].strip()
        if name == "UID" and out["uid"] is None:
            out["uid"] = value
        elif name == "FN" and out["fn"] is None:
            out["fn"] = value
        elif name == "BDAY" and out["bday"] is None:
            out["bday"] = line.strip()
        elif name == "NOTE" and out["note"] is None:
            out["note"] = value
        elif name == "CATEGORIES":
            vals = line.split(":", 1)[1]
            out["categories"] = [v.strip() for v in vals.split(",") if v.strip()]
        elif name == "X-ABDATE":
            if item_id not in abdates:
                abdate_order.append(item_id)
            abdates[item_id] = value
        elif name == "X-ABLABEL":
            ablabels[item_id] = _decode_apple_label(value)
        elif name in ("ANNIVERSARY", "X-ANNIVERSARY"):
            anniversaries.append(value)
    for item_id in abdate_order:
        out["labeled_dates"].append(
            {"date": abdates[item_id], "label": ablabels.get(item_id)})
    for value in anniversaries:
        out["labeled_dates"].append({"date": value, "label": "Anniversary"})
    return out


def note_blacklisted(note, marker):
    """True if the token (e.g. '#NB') appears as a whole word in the NOTE."""
    if not note:
        return False
    pattern = re.escape(marker) + r"(?!\w)"
    return re.search(pattern, note, re.IGNORECASE) is not None


# --- Date parsing ---------------------------------------------------------

_RE_VCARD4 = re.compile(r"^--(\d{2})-?(\d{2})$")
_RE_DASHED = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_RE_BASIC = re.compile(r"^(\d{4})(\d{2})(\d{2})$")


def parse_date(line):
    """Date property line -> (month, day, year|None), or None if unparseable.

    Source-agnostic: works for BDAY, ANNIVERSARY, and X-ABDATE values (same
    date formats: ISO, basic, vCard4 ``--MM-DD``/``--MMDD``, time suffix,
    ``X-APPLE-OMIT-YEAR``/``1604`` sentinel).
    """
    head, sep, value = line.partition(":")
    if not sep:
        return None
    omit = "OMIT-YEAR" in head.upper()
    value = value.strip().split("T", 1)[0]
    m = _RE_VCARD4.match(value)
    if m:
        return (int(m.group(1)), int(m.group(2)), None)
    for rx in (_RE_DASHED, _RE_BASIC):
        m = rx.match(value)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if omit or y == 1604:
                y = None
            return (mo, d, y)
    return None


def dates_for_type(contact, type_name, type_cfg):
    """Extract a date_type's occurrences from a parsed contact.

    Returns a list of ``(month, day, year_or_None, label)`` tuples.

    - ``source == "BDAY"``: parse ``contact["bday"]``; label is ``type_name``.
    - otherwise (labeled source): scan ``contact["labeled_dates"]`` and select
      entries whose decoded label matches ``type_cfg["apple_label"]``
      (case-insensitive), OR, when ``match == "x-abdate-any"``, any entry whose
      label is NOT in ``type_cfg["claimed_labels"]`` (lower-cased labels claimed
      by other, more specific enabled types). The returned label is the entry's
      decoded label (possibly ``None``).

    Unparseable dates are skipped.
    """
    out = []
    if type_cfg.get("source") == "BDAY":
        bday = contact.get("bday")
        if not bday:
            return out
        parsed = parse_date(bday)
        if parsed:
            out.append((parsed[0], parsed[1], parsed[2], type_name))
        return out
    apple_label = type_cfg.get("apple_label")
    apple_label_lc = apple_label.lower() if apple_label else None
    catch_all = type_cfg.get("match") == "x-abdate-any"
    claimed = {c.lower() for c in type_cfg.get("claimed_labels", [])}
    for entry in contact.get("labeled_dates", []):
        label = entry.get("label")
        label_lc = label.lower() if label else None
        if apple_label_lc is not None:
            if label_lc != apple_label_lc:
                continue
        elif catch_all:
            if label_lc is not None and label_lc in claimed:
                continue
        else:
            continue
        parsed = parse_date("X:" + entry.get("date", ""))
        if not parsed:
            continue
        out.append((parsed[0], parsed[1], parsed[2], label))
    return out


# --- Date helpers ---------------------------------------------------------

def ordinal(n):
    """English ordinal: 1->'1st', 2->'2nd', 3->'3rd', 11->'11th', 21->'21st'."""
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def format_date(month, day, year, date_format, months):
    """Render a date via a user-controlled ``date_format`` (str.format).

    Placeholders: ``{day}`` (numeric), ``{month}`` (name from ``months``),
    ``{month_num}`` (numeric), ``{year}`` (empty when unknown), and the
    English-only convenience ``{day_english}`` (e.g. ``10th``).
    """
    return date_format.format(
        day=day,
        day_english=ordinal(day),
        month=months[month],
        month_num=month,
        year=year if year is not None else "",
    )


def date_formatted(month, day, months):
    return format_date(month, day, None, DEFAULT_DATE_FORMAT, months)


# --- iCal duration / alarm-trigger ---------------------------------------

def format_ical_duration(delta):
    total = int(delta.total_seconds())
    if total == 0:
        return "PT0S"
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    out = sign + "P"
    if days:
        out += "%dD" % days
    if hours or minutes or seconds:
        out += "T"
        if hours:
            out += "%dH" % hours
        if minutes:
            out += "%dM" % minutes
        if seconds:
            out += "%dS" % seconds
    return out


def alarm_trigger(days_before, at):
    h, m = (int(x) for x in at.split(":"))
    return format_ical_duration(
        _dt.timedelta(days=-int(days_before), hours=h, minutes=m)
    )


_ISO_DURATION_RE = re.compile(
    r"^(?P<sign>[+-]?)P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:(?P<s>\d+)S)?)?$"
)


def parse_iso_duration(value):
    """ISO 8601 duration (subset) -> timedelta; ValueError if invalid.

    Supports days and time components: ``PT1M``, ``PT1M30S``, ``PT0S``,
    ``P1DT2H3M4S``. At least one numeric component is required.
    """
    m = _ISO_DURATION_RE.match(value or "")
    if not m:
        raise ValueError("invalid ISO 8601 duration: %r" % (value,))
    parts = (m.group("days"), m.group("h"), m.group("m"), m.group("s"))
    if all(p is None for p in parts):
        raise ValueError("empty ISO 8601 duration: %r" % (value,))
    days, hours, mins, secs = (int(p) if p else 0 for p in parts)
    delta = _dt.timedelta(days=days, hours=hours, minutes=mins, seconds=secs)
    return -delta if m.group("sign") == "-" else delta


# --- ICS escaping / folding ----------------------------------------------

def ics_escape(value):
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n").replace("\r", "")
    value = value.replace(",", "\\,").replace(";", "\\;")
    return value


def fold_line(line):
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        limit = 75 if not out else 74
        if len(cur) + len(enc) > limit:
            out.append(cur)
            cur = b" " + enc
        else:
            cur += enc
    out.append(cur)
    return "\r\n".join(p.decode("utf-8") for p in out)


# --- Config ---------------------------------------------------------------

DEFAULT_CONFIG = {
    "future_days": 730,
    "past_days": 365,
    "blacklist_note_marker": "#NB",
    "month_names": DEFAULT_MONTHS,
    "date_format": DEFAULT_DATE_FORMAT,
    "suffix": "-auto-contact-dates",
    "displayname_prefix": "Contact dates",
    "prodid": PRODID,
    "collections": {
        "*/contacts": {"enabled": True},
        "*/archived-contacts": {"enabled": False},
    },
    "date_types": {
        "birthday": {
            "enabled": True,
            "source": "BDAY",
            "category": "Birthday",
            "alarms": _DEFAULT_ALARMS,
            "templates": {
                "summary_with_count": "🎂 {name} turns {count}",
                "summary_no_count": "🎂 {name}'s birthday",
                "alarm_before_with_count": "🎂 {name} turns {count} on {date}",
                "alarm_before_no_count": "🎂 {name}'s birthday on {date}",
                "alarm_day_with_count": "🎂 {name} turns {count} today",
                "alarm_day_no_count": "🎂 {name}'s birthday today",
            },
        },
        "anniversary": {
            "enabled": True,
            "source": "ANNIVERSARY",
            "apple_label": "Anniversary",
            "category": "Anniversary",
            "alarms": _DEFAULT_ALARMS,
            "templates": {
                "summary_with_count": "💍 {name} — {ordinal} anniversary",
                "summary_no_count": "💍 {name}'s anniversary",
                "alarm_before_with_count":
                    "💍 {name}'s {ordinal} anniversary on {date}",
                "alarm_before_no_count": "💍 {name}'s anniversary on {date}",
                "alarm_day_with_count":
                    "💍 {name}'s {ordinal} anniversary today",
                "alarm_day_no_count": "💍 {name}'s anniversary today",
            },
        },
        "other_dates": {
            "enabled": False,
            "match": "x-abdate-any",
            "category": "Important date",
            "alarms": _DEFAULT_ALARMS,
            "templates": {
                "summary_with_count": "📅 {name} — {label} ({count})",
                "summary_no_count": "📅 {name} — {label}",
                "alarm_before_with_count":
                    "📅 {name} — {label} ({count}) on {date}",
                "alarm_before_no_count": "📅 {name} — {label} on {date}",
                "alarm_day_with_count": "📅 {name} — {label} ({count}) today",
                "alarm_day_no_count": "📅 {name} — {label} today",
            },
        },
    },
}


# --- Occurrence window -----------------------------------------------------

def _safe_date(year, month, day):
    if month == 2 and day == 29:
        try:
            return _dt.date(year, 2, 29)
        except ValueError:
            return _dt.date(year, 2, 28)
    return _dt.date(year, month, day)


def occurrences_known(today, month, day, birth_year, future_days, past_days):
    """List of (date, age) for year-known contacts within the window
    [today - past_days, today + future_days]."""
    earliest = today - _dt.timedelta(days=past_days)
    latest = today + _dt.timedelta(days=future_days)
    out = []
    for year in range(earliest.year, latest.year + 1):
        d = _safe_date(year, month, day)
        if earliest <= d <= latest:
            out.append((d, year - birth_year))
    out.sort()
    return out


# --- Event building --------------------------------------------------------

def render(tpl, **ctx):
    return tpl.format(**ctx)


def _ctx(name, count, month, day, year, months, label=None,
         date_format=DEFAULT_DATE_FORMAT):
    """Template context. ``count`` = years since the base date (turns-age /
    Nth); aliases ``{age}``/``{years}`` share its value, ``{ordinal}`` (and its
    explicit alias ``{count_english}``) is ``ordinal(count)``. All count-derived
    keys are empty when ``count`` is ``None`` (year unknown). ``{label}`` is the
    decoded date label or empty. ``{date}`` is built from ``date_format``."""
    cnt = count if count is not None else ""
    eng = ordinal(count) if count is not None else ""
    return {
        "name": name,
        "count": cnt,
        "age": cnt,
        "years": cnt,
        "ordinal": eng,
        "count_english": eng,
        "label": label if label is not None else "",
        "day": day,
        "date": format_date(month, day, year, date_format, months),
        "year": year if year is not None else "",
    }


def _alarm_text(name, count, month, day, label, days_before, type_cfg,
                months, date_format=DEFAULT_DATE_FORMAT):
    """Render the alarm/reminder line for a given lead time.

    ``days_before > 0`` -> the ``alarm_before_*`` template; otherwise the
    ``alarm_day_*`` template. ``*_with_count`` when the year is known, else
    ``*_no_count``."""
    tpls = type_cfg["templates"]
    ctx = _ctx(name, count, month, day, None, months, label=label,
               date_format=date_format)
    if int(days_before) > 0:
        key = ("alarm_before_with_count" if count is not None
               else "alarm_before_no_count")
    else:
        key = ("alarm_day_with_count" if count is not None
               else "alarm_day_no_count")
    return render(tpls[key], **ctx)


def _valarms(name, count, month, day, label, type_cfg, months,
             date_format=DEFAULT_DATE_FORMAT):
    lines = []
    for al in type_cfg.get("alarms", []):
        if al.get("type", "alarm") == "event":
            continue  # rendered as a separate reminder VEVENT instead
        desc = ics_escape(_alarm_text(name, count, month, day, label,
                                      al["days_before"], type_cfg, months,
                                      date_format))
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            "TRIGGER:" + alarm_trigger(al["days_before"], al["at"]),
            "DESCRIPTION:" + desc,
            "END:VALARM",
        ]
    return lines


def _utcstamp():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _build_event(type_name, source_uid, uid_suffix, name, start, count, label,
                 type_cfg, months, rrule, date_format=DEFAULT_DATE_FORMAT):
    tpls = type_cfg["templates"]
    category = type_cfg.get("category", "")
    skey = "summary_with_count" if count is not None else "summary_no_count"
    summary = ics_escape(
        render(tpls[skey],
               **_ctx(name, count, start.month, start.day, start.year, months,
                      label=label, date_format=date_format))
    )
    end = start + _dt.timedelta(days=1)
    lines = [
        "BEGIN:VEVENT",
        "UID:auto-%s-%s@radicale" % (type_name, uid_suffix),
        "DTSTAMP:" + _utcstamp(),
        "DTSTART;VALUE=DATE:%s" % start.strftime("%Y%m%d"),
        "DTEND;VALUE=DATE:%s" % end.strftime("%Y%m%d"),
    ]
    if rrule:
        lines.append("RRULE:FREQ=YEARLY")
    lines += [
        "SUMMARY:" + summary,
        "TRANSP:TRANSPARENT",
        "CATEGORIES:" + category,
        "X-AUTO-CONTACT-DATE-SOURCE:" + source_uid,
    ]
    lines += _valarms(name, count, start.month, start.day, label, type_cfg,
                      months, date_format)
    lines.append("END:VEVENT")
    return "\r\n".join(fold_line(x) for x in lines)


def build_event_known(type_name, uid, name, date, count, label, type_cfg,
                      months, date_format=DEFAULT_DATE_FORMAT):
    return _build_event(type_name, uid, "%s-%d" % (uid, date.year), name, date,
                        count, label, type_cfg, months, False, date_format)


def build_event_unknown(type_name, uid, name, month, day, start_year, label,
                        type_cfg, months, date_format=DEFAULT_DATE_FORMAT):
    start = _safe_date(start_year, month, day)
    return _build_event(type_name, uid, uid, name, start, None, label,
                        type_cfg, months, True, date_format)


# --- Reminder events (alarm "type": "event") ------------------------------

def _build_reminder_event(type_name, uid_suffix, name, start_dt, duration,
                          text, category, source_uid, rrule):
    """A timed reminder VEVENT carrying the alarm text as its ``SUMMARY``, plus
    a single ``TRIGGER:PT0S`` VALARM so even clients that ignore alarm
    descriptions still notify with the right text. ``start_dt`` is a floating
    local DATE-TIME (no ``Z``/``TZID``), so no ``VTIMEZONE`` is needed."""
    end_dt = start_dt + duration
    esc = ics_escape(text)
    lines = [
        "BEGIN:VEVENT",
        "UID:auto-%s-%s@radicale" % (type_name, uid_suffix),
        "DTSTAMP:" + _utcstamp(),
        "DTSTART:" + start_dt.strftime("%Y%m%dT%H%M%S"),
        "DTEND:" + end_dt.strftime("%Y%m%dT%H%M%S"),
    ]
    if rrule:
        lines.append("RRULE:FREQ=YEARLY")
    lines += [
        "SUMMARY:" + esc,
        "TRANSP:TRANSPARENT",
        "CATEGORIES:" + category,
        "X-AUTO-CONTACT-DATE-SOURCE:" + source_uid,
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "TRIGGER:PT0S",
        "DESCRIPTION:" + esc,
        "END:VALARM",
        "END:VEVENT",
    ]
    return "\r\n".join(fold_line(x) for x in lines)


def _reminder_start(occ_date, days_before, at):
    """Floating-local datetime ``days_before`` days before ``occ_date`` at
    ``at`` (``HH:MM``)."""
    h, m = (int(x) for x in at.split(":"))
    rdate = occ_date - _dt.timedelta(days=int(days_before))
    return _dt.datetime(rdate.year, rdate.month, rdate.day, h, m)


def build_reminder_event_known(type_name, uid, name, occ_date, count, label,
                               alarm, type_cfg, months,
                               date_format=DEFAULT_DATE_FORMAT, index=0):
    start_dt = _reminder_start(occ_date, alarm["days_before"], alarm["at"])
    duration = parse_iso_duration(
        alarm.get("duration", DEFAULT_REMINDER_DURATION))
    text = _alarm_text(name, count, occ_date.month, occ_date.day, label,
                       alarm["days_before"], type_cfg, months, date_format)
    uid_suffix = "%s-%d-r%d" % (uid, occ_date.year, index)
    return _build_reminder_event(
        type_name, uid_suffix, name, start_dt, duration, text,
        type_cfg.get("category", ""), uid, False)


def build_reminder_event_unknown(type_name, uid, name, month, day, start_year,
                                 label, alarm, type_cfg, months,
                                 date_format=DEFAULT_DATE_FORMAT, index=0):
    occ_date = _safe_date(start_year, month, day)
    start_dt = _reminder_start(occ_date, alarm["days_before"], alarm["at"])
    duration = parse_iso_duration(
        alarm.get("duration", DEFAULT_REMINDER_DURATION))
    text = _alarm_text(name, None, month, day, label, alarm["days_before"],
                       type_cfg, months, date_format)
    uid_suffix = "%s-r%d" % (uid, index)
    return _build_reminder_event(
        type_name, uid_suffix, name, start_dt, duration, text,
        type_cfg.get("category", ""), uid, True)


# --- Desired set ----------------------------------------------------------

def _wrap(vevent, prodid):
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:" + prodid,
        vevent, "END:VCALENDAR", "",
    ])


def _enabled_date_types(cfg):
    """Ordered list of (type_name, type_cfg) for enabled date_types, with
    ``claimed_labels`` injected into any catch-all type (labels owned by the
    more-specific enabled types, so first-match-wins)."""
    date_types = cfg.get("date_types", {})
    claimed = [
        tc["apple_label"].lower()
        for tc in date_types.values()
        if tc.get("enabled") and tc.get("apple_label")
    ]
    out = []
    for name, tc in date_types.items():
        if not tc.get("enabled"):
            continue
        if tc.get("match") == "x-abdate-any":
            tc = dict(tc, claimed_labels=claimed)
        out.append((name, tc))
    return out


def desired_items(contacts, today, cfg):
    """Contacts -> {filename: VCALENDAR text} for the single combined
    collection. Iterates every enabled date_type per contact; all items land
    in one dict. ``#NB`` in the NOTE skips the whole contact."""
    marker = cfg.get("blacklist_note_marker", "#NB")
    future_days = cfg.get("future_days", 730)
    past_days = cfg.get("past_days", 365)
    prodid = cfg.get("prodid", PRODID)
    months = cfg.get("month_names", DEFAULT_MONTHS)
    date_format = cfg.get("date_format", DEFAULT_DATE_FORMAT)
    enabled = _enabled_date_types(cfg)
    out = {}
    for c in contacts:
        uid = c.get("uid")
        if not uid:
            continue
        if note_blacklisted(c.get("note"), marker):
            continue
        name = c.get("fn") or "?"
        for type_name, type_cfg in enabled:
            event_alarms = [
                (i, al) for i, al in enumerate(type_cfg.get("alarms", []))
                if al.get("type", "alarm") == "event"
            ]
            for month, day, year, label in dates_for_type(c, type_name,
                                                          type_cfg):
                if year is None:
                    today_occ = _safe_date(today.year, month, day)
                    start_year = (today.year if today_occ >= today
                                  else today.year + 1)
                    ev = build_event_unknown(
                        type_name, uid, name, month, day, start_year, label,
                        type_cfg, months, date_format)
                    out["auto-%s-%s.ics" % (type_name, uid)] = _wrap(
                        ev, prodid)
                    for i, al in event_alarms:
                        rev = build_reminder_event_unknown(
                            type_name, uid, name, month, day, start_year,
                            label, al, type_cfg, months, date_format, i)
                        fn = "auto-%s-%s-r%d.ics" % (type_name, uid, i)
                        out[fn] = _wrap(rev, prodid)
                else:
                    for date, count in occurrences_known(
                            today, month, day, year, future_days, past_days):
                        ev = build_event_known(
                            type_name, uid, name, date, count, label,
                            type_cfg, months, date_format)
                        out["auto-%s-%s-%d.ics" % (
                            type_name, uid, date.year)] = _wrap(ev, prodid)
                        for i, al in event_alarms:
                            days_before = int(al["days_before"])
                            rdate = date - _dt.timedelta(days=days_before)
                            # Prune spent "before" reminders once their day has
                            # passed; keep day-of (0d) reminders (they follow
                            # the occurrence window, like the main event).
                            if days_before > 0 and rdate < today:
                                continue
                            rev = build_reminder_event_known(
                                type_name, uid, name, date, count, label,
                                al, type_cfg, months, date_format, i)
                            fn = "auto-%s-%s-%d-r%d.ics" % (
                                type_name, uid, date.year, i)
                            out[fn] = _wrap(rev, prodid)
    return out


# --- Reconcile ------------------------------------------------------------

def _norm(text):
    keep = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith(("DTSTAMP", "REV")):
            continue
        keep.append(line)
    return "\n".join(keep)


def reconcile(desired, existing):
    """(creates, updates, deletes) between desired and existing items."""
    creates, updates = {}, {}
    for name, content in desired.items():
        if name not in existing:
            creates[name] = content
        elif _norm(existing[name]) != _norm(content):
            updates[name] = content
    deletes = sorted(n for n in existing if n not in desired)
    return creates, updates, deletes


# --- Config loading --------------------------------------------------------

def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path, raw=None):
    if raw is None and path:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    return _deep_merge(DEFAULT_CONFIG, raw or {})


# --- Filesystem layer ------------------------------------------------------

def read_existing(coll_dir):
    """Read only 'managed' items (auto-*.ics) from a collection."""
    out = {}
    if not os.path.isdir(coll_dir):
        return out
    for fn in os.listdir(coll_dir):
        if fn.startswith("auto-") and fn.endswith(".ics"):
            with open(os.path.join(coll_dir, fn), "r", encoding="utf-8",
                      newline="") as fh:
                out[fn] = fh.read()
    return out


def write_atomic(path, content):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def ensure_collection(coll_dir, displayname):
    os.makedirs(coll_dir, exist_ok=True)
    props = os.path.join(coll_dir, ".Radicale.props")
    if not os.path.exists(props):
        write_atomic(props, json.dumps({
            "tag": "VCALENDAR",
            "C:supported-calendar-component-set": "VEVENT",
            "D:displayname": displayname,
        }))


def _source_displayname(ab_dir):
    props = os.path.join(ab_dir, ".Radicale.props")
    if os.path.exists(props):
        try:
            with open(props, encoding="utf-8") as fh:
                return json.load(fh).get("D:displayname")
        except (ValueError, OSError):
            pass
    return None


def contact_dates_displayname(ab_dir, coll, prefix):
    """Derive '<prefix> (X)' from the source addressbook displayname
    ('Contacts (Team)' -> 'Contact dates (Team)'), preserving casing."""
    src = _source_displayname(ab_dir)
    if src:
        m = re.search(r"\(([^)]+)\)", src)
        if m:
            return "%s (%s)" % (prefix, m.group(1))
    return "%s (%s)" % (prefix, coll.split("/")[0])


def invalidate_cache(coll_dir):
    cache = os.path.join(coll_dir, ".Radicale.cache")
    if os.path.isdir(cache):
        shutil.rmtree(cache, ignore_errors=True)


# --- Orchestration ---------------------------------------------------------

def discover_contacts(ab_dir):
    out = []
    for fn in sorted(os.listdir(ab_dir)):
        if fn.endswith(".vcf"):
            with open(os.path.join(ab_dir, fn), "r", encoding="utf-8",
                      errors="replace", newline="") as fh:
                out.append(parse_vcard(fh.read()))
    return out


def _is_addressbook(cdir):
    props = os.path.join(cdir, ".Radicale.props")
    if os.path.exists(props):
        try:
            with open(props, encoding="utf-8") as fh:
                if json.load(fh).get("tag") == "VADDRESSBOOK":
                    return True
        except (ValueError, OSError):
            pass
    return any(fn.endswith(".vcf") for fn in os.listdir(cdir))


def discover_addressbooks(root, suffix="-auto-contact-dates"):
    """Discover all <user>/<collection> addressbooks (excl. generated ones)."""
    out = []
    if not os.path.isdir(root):
        return out
    for user in sorted(os.listdir(root)):
        udir = os.path.join(root, user)
        if not os.path.isdir(udir):
            continue
        for sub in sorted(os.listdir(udir)):
            if sub.endswith(suffix):
                continue
            cdir = os.path.join(udir, sub)
            if os.path.isdir(cdir) and _is_addressbook(cdir):
                out.append("%s/%s" % (user, sub))
    return out


def _collection_settings(coll, collections):
    """First config pattern (fnmatch) that matches the collection, or None."""
    for pattern, settings in collections.items():
        if fnmatch.fnmatch(coll, pattern):
            return settings
    return None


def sync(root, cfg, today, dry_run=False, only_collection=None, verbose=False):
    summary = {"create": 0, "update": 0, "delete": 0, "collections": {}}
    collections_cfg = cfg.get("collections", {})
    suffix = cfg.get("suffix", "-auto-contact-dates")
    prefix = cfg.get("displayname_prefix", "Contact dates")
    for coll in discover_addressbooks(root, suffix):
        if only_collection and coll != only_collection:
            continue
        settings = _collection_settings(coll, collections_cfg)
        if settings is None or not settings.get("enabled", True):
            continue
        ab_dir = os.path.join(root, coll)
        contacts = discover_contacts(ab_dir)
        desired = desired_items(contacts, today, cfg)
        cdates_dir = os.path.join(root, coll + suffix)
        existing = read_existing(cdates_dir)
        creates, updates, deletes = reconcile(desired, existing)
        summary["create"] += len(creates)
        summary["update"] += len(updates)
        summary["delete"] += len(deletes)
        summary["collections"][coll] = (len(creates), len(updates),
                                        len(deletes))
        if verbose:
            for n in list(creates):
                print("   + %s/%s" % (coll, n))
            for n in list(updates):
                print("   ~ %s/%s" % (coll, n))
            for n in deletes:
                print("   - %s/%s" % (coll, n))
        if dry_run or not (creates or updates or deletes):
            continue
        ensure_collection(
            cdates_dir, contact_dates_displayname(ab_dir, coll, prefix))
        changed = dict(creates)
        changed.update(updates)
        for name, content in changed.items():
            write_atomic(os.path.join(cdates_dir, name), content)
        for name in deletes:
            try:
                os.remove(os.path.join(cdates_dir, name))
            except FileNotFoundError:
                pass
        invalidate_cache(cdates_dir)
    return summary


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Contact-dates sync")
    ap.add_argument("--config", default="/plugins/contact-dates.config.json")
    ap.add_argument("--root", default="/data/collections/collection-root")
    ap.add_argument("--collection")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    cfg = load_config(args.config if os.path.exists(args.config) else None)
    today = _dt.date.today()
    summary = sync(args.root, cfg, today, dry_run=args.dry_run,
                   only_collection=args.collection, verbose=args.verbose)
    for coll, (c, u, dl) in summary["collections"].items():
        print("%s: +%d ~%d -%d" % (coll, c, u, dl))
    tag = " (dry-run)" if args.dry_run else ""
    print("TOTAL: +%d ~%d -%d%s" % (summary["create"], summary["update"],
                                     summary["delete"], tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

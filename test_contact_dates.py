import datetime as dt
import json
import os
import tempfile
import unittest

import contact_dates as cd

FIXTURES = os.path.join(
    os.path.dirname(__file__), "tests", "fixtures"
)


# --- pure helpers -------------------------------------------------

class TestParseVcard(unittest.TestCase):
    SAMPLE = (
        "BEGIN:VCARD\r\nVERSION:3.0\r\n"
        "UID:abc-123\r\n"
        "BDAY;X-APPLE-OMIT-YEAR=1604:1604-07-20\r\n"
        "FN:Casey Example\r\n"
        "CATEGORIES:Vrienden,NoBirthday\r\n"
        "END:VCARD\r\n"
    )

    def test_extracts_fields(self):
        c = cd.parse_vcard(self.SAMPLE)
        self.assertEqual(c["uid"], "abc-123")
        self.assertEqual(c["fn"], "Casey Example")
        self.assertEqual(c["bday"], "BDAY;X-APPLE-OMIT-YEAR=1604:1604-07-20")
        self.assertIn("NoBirthday", c["categories"])

    def test_unfolds_long_lines(self):
        folded = "FN:Voornaam Achter\r\n naam\r\n"
        c = cd.parse_vcard("BEGIN:VCARD\r\n" + folded + "END:VCARD\r\n")
        self.assertEqual(c["fn"], "Voornaam Achternaam")

    def test_extracts_note(self):
        v = ("BEGIN:VCARD\r\nUID:x\r\nFN:Y\r\n"
             "NOTE:Vriend van vroeger #NB niet vergeten\r\nEND:VCARD\r\n")
        c = cd.parse_vcard(v)
        self.assertEqual(c["note"], "Vriend van vroeger #NB niet vergeten")

    def test_keeps_existing_keys(self):
        c = cd.parse_vcard(self.SAMPLE)
        for k in ("uid", "fn", "bday", "note", "categories", "labeled_dates"):
            self.assertIn(k, c)
        self.assertEqual(c["labeled_dates"], [])


class TestLabeledDates(unittest.TestCase):
    def test_apple_labeled_anniversary(self):
        v = ("BEGIN:VCARD\r\nUID:x\r\nFN:Y\r\n"
             "item1.X-ABDATE;TYPE=pref:2002-10-26\r\n"
             "item1.X-ABLABEL:_$!<Anniversary>!$_\r\nEND:VCARD\r\n")
        c = cd.parse_vcard(v)
        self.assertEqual(c["labeled_dates"],
                         [{"date": "2002-10-26", "label": "Anniversary"}])

    def test_standard_anniversary(self):
        v = "BEGIN:VCARD\r\nUID:x\r\nANNIVERSARY:1999-06-15\r\nEND:VCARD\r\n"
        c = cd.parse_vcard(v)
        self.assertIn({"date": "1999-06-15", "label": "Anniversary"},
                      c["labeled_dates"])

    def test_x_anniversary(self):
        v = "BEGIN:VCARD\r\nUID:x\r\nX-ANNIVERSARY:1999-06-15\r\nEND:VCARD\r\n"
        c = cd.parse_vcard(v)
        self.assertIn({"date": "1999-06-15", "label": "Anniversary"},
                      c["labeled_dates"])

    def test_custom_labeled_date(self):
        v = ("BEGIN:VCARD\r\nUID:x\r\n"
             "item2.X-ABDATE:2015-09-01\r\nitem2.X-ABLABEL:Graduation\r\n"
             "END:VCARD\r\n")
        c = cd.parse_vcard(v)
        self.assertEqual(c["labeled_dates"],
                         [{"date": "2015-09-01", "label": "Graduation"}])

    def test_unlabeled_abdate_label_none(self):
        v = ("BEGIN:VCARD\r\nUID:x\r\n"
             "item3.X-ABDATE:2010-01-02\r\nEND:VCARD\r\n")
        c = cd.parse_vcard(v)
        self.assertEqual(c["labeled_dates"],
                         [{"date": "2010-01-02", "label": None}])


class TestParseDate(unittest.TestCase):
    def test_full_iso(self):
        self.assertEqual(cd.parse_date("BDAY:1971-03-19"), (3, 19, 1971))

    def test_basic(self):
        self.assertEqual(cd.parse_date("BDAY:19860602"), (6, 2, 1986))

    def test_apple_omit_year(self):
        self.assertEqual(
            cd.parse_date("BDAY;X-APPLE-OMIT-YEAR=1604:1604-07-20"), (7, 20, None)
        )

    def test_sentinel_without_param(self):
        self.assertEqual(cd.parse_date("BDAY:1604-06-03"), (6, 3, None))

    def test_vcard4_dash(self):
        self.assertEqual(cd.parse_date("BDAY:--09-30"), (9, 30, None))

    def test_vcard4_dash_basic(self):
        self.assertEqual(cd.parse_date("BDAY:--0930"), (9, 30, None))

    def test_strips_time(self):
        self.assertEqual(cd.parse_date("BDAY:1986-06-02T00:00:00"), (6, 2, 1986))

    def test_unparseable(self):
        self.assertIsNone(cd.parse_date("BDAY:nonsense"))

    def test_anniversary_date_value(self):
        # parse_date is source-agnostic; bare ANNIVERSARY value parses too.
        self.assertEqual(cd.parse_date("ANNIVERSARY:2002-10-26"), (10, 26, 2002))


class TestDatesForType(unittest.TestCase):
    def _contact(self):
        return {
            "uid": "u1", "fn": "Casey Example",
            "bday": "BDAY:1980-04-10",
            "labeled_dates": [
                {"date": "2002-10-26", "label": "Anniversary"},
                {"date": "2015-09-01", "label": "Graduation"},
                {"date": "2010-01-02", "label": None},
            ],
        }

    def test_birthday_source_bday(self):
        cfg = {"source": "BDAY"}
        self.assertEqual(
            cd.dates_for_type(self._contact(), "birthday", cfg),
            [(4, 10, 1980, "birthday")])

    def test_birthday_missing_bday_empty(self):
        cfg = {"source": "BDAY"}
        contact = {"uid": "u", "bday": None, "labeled_dates": []}
        self.assertEqual(cd.dates_for_type(contact, "birthday", cfg), [])

    def test_anniversary_via_apple_label(self):
        cfg = {"apple_label": "Anniversary"}
        self.assertEqual(
            cd.dates_for_type(self._contact(), "anniversary", cfg),
            [(10, 26, 2002, "Anniversary")])

    def test_anniversary_apple_label_case_insensitive(self):
        cfg = {"apple_label": "anniversary"}
        self.assertEqual(
            cd.dates_for_type(self._contact(), "anniversary", cfg),
            [(10, 26, 2002, "Anniversary")])

    def test_catch_all_picks_leftover_labels(self):
        # 'Anniversary' is claimed by the anniversary type -> excluded.
        cfg = {"match": "x-abdate-any", "claimed_labels": ["anniversary"]}
        self.assertEqual(
            cd.dates_for_type(self._contact(), "other_dates", cfg),
            [(9, 1, 2015, "Graduation"), (1, 2, 2010, None)])

    def test_catch_all_no_claims_takes_all_labeled(self):
        cfg = {"match": "x-abdate-any"}
        self.assertEqual(
            cd.dates_for_type(self._contact(), "other_dates", cfg),
            [(10, 26, 2002, "Anniversary"),
             (9, 1, 2015, "Graduation"),
             (1, 2, 2010, None)])

    def test_skips_unparseable_labeled_date(self):
        cfg = {"apple_label": "Anniversary"}
        contact = {"uid": "u", "bday": None, "labeled_dates": [
            {"date": "nonsense", "label": "Anniversary"}]}
        self.assertEqual(cd.dates_for_type(contact, "anniversary", cfg), [])


class TestFormatting(unittest.TestCase):
    def test_ordinal_english(self):
        self.assertEqual(cd.ordinal(1), "1st")
        self.assertEqual(cd.ordinal(2), "2nd")
        self.assertEqual(cd.ordinal(3), "3rd")
        self.assertEqual(cd.ordinal(11), "11th")
        self.assertEqual(cd.ordinal(21), "21st")

    def test_date_formatted_english_default(self):
        self.assertEqual(cd.date_formatted(3, 19, cd.DEFAULT_MONTHS), "19 March")

    def test_date_formatted_custom(self):
        nl = ["", "januari", "februari", "maart"] + [""] * 9
        self.assertEqual(cd.date_formatted(3, 19, nl), "19 maart")


class TestPlaceholders(unittest.TestCase):
    """Task 4: generic template placeholders via _ctx/render."""

    def _ctx(self, count=25, label="Anniversary"):
        return cd._ctx("Casey Example", count, 10, 26, 2002,
                       cd.DEFAULT_MONTHS, label=label)

    def test_count_age_years_are_aliases(self):
        ctx = self._ctx(count=25)
        self.assertEqual(cd.render("{count}", **ctx), "25")
        self.assertEqual(cd.render("{age}", **ctx), "25")
        self.assertEqual(cd.render("{years}", **ctx), "25")

    def test_ordinal_is_ordinal_of_count(self):
        self.assertEqual(cd.render("{ordinal}", **self._ctx(count=25)), "25th")
        self.assertEqual(cd.render("{ordinal}", **self._ctx(count=21)), "21st")

    def test_label_placeholder(self):
        self.assertEqual(
            cd.render("{label}", **self._ctx(label="Graduation")), "Graduation")

    def test_name_day_date_year(self):
        ctx = self._ctx()
        self.assertEqual(cd.render("{name}", **ctx), "Casey Example")
        self.assertEqual(cd.render("{day}", **ctx), "26")
        self.assertEqual(cd.render("{date}", **ctx), "26 October")
        self.assertEqual(cd.render("{year}", **ctx), "2002")

    def test_count_aliases_empty_when_year_unknown(self):
        ctx = cd._ctx("X", None, 7, 20, None, cd.DEFAULT_MONTHS, label="Birthday")
        self.assertEqual(cd.render("{count}", **ctx), "")
        self.assertEqual(cd.render("{age}", **ctx), "")
        self.assertEqual(cd.render("{years}", **ctx), "")
        self.assertEqual(cd.render("{ordinal}", **ctx), "")
        self.assertEqual(cd.render("{year}", **ctx), "")

    def test_label_empty_when_none(self):
        ctx = cd._ctx("X", 5, 7, 20, 2020, cd.DEFAULT_MONTHS, label=None)
        self.assertEqual(cd.render("{label}", **ctx), "")


class TestDateFormat(unittest.TestCase):
    def test_default_constant(self):
        self.assertEqual(cd.DEFAULT_DATE_FORMAT, "{day} {month}")

    def test_default_day_first(self):
        self.assertEqual(
            cd.format_date(4, 10, 2026, "{day} {month}", cd.DEFAULT_MONTHS),
            "10 April")

    def test_us_month_first(self):
        self.assertEqual(
            cd.format_date(4, 10, 2026, "{month} {day}", cd.DEFAULT_MONTHS),
            "April 10")

    def test_day_english_suffix(self):
        self.assertEqual(
            cd.format_date(4, 10, 2026, "{month} {day_english}",
                           cd.DEFAULT_MONTHS),
            "April 10th")

    def test_month_num_and_year(self):
        self.assertEqual(
            cd.format_date(4, 10, 2026, "{month_num}/{day}/{year}",
                           cd.DEFAULT_MONTHS),
            "4/10/2026")

    def test_year_none_renders_empty(self):
        self.assertEqual(
            cd.format_date(4, 10, None, "{day} {month}{year}",
                           cd.DEFAULT_MONTHS),
            "10 April")

    def test_ctx_count_english_alias_of_ordinal(self):
        ctx = cd._ctx("X", 25, 10, 26, 2002, cd.DEFAULT_MONTHS)
        self.assertEqual(cd.render("{count_english}", **ctx), "25th")
        self.assertEqual(cd.render("{ordinal}", **ctx), "25th")

    def test_ctx_count_english_empty_when_unknown(self):
        ctx = cd._ctx("X", None, 7, 20, None, cd.DEFAULT_MONTHS)
        self.assertEqual(cd.render("{count_english}", **ctx), "")

    def test_ctx_custom_date_format_drives_date(self):
        ctx = cd._ctx("X", 25, 10, 26, 2002, cd.DEFAULT_MONTHS,
                      date_format="{month} {day_english}")
        self.assertEqual(cd.render("{date}", **ctx), "October 26th")

    def test_config_default_date_format(self):
        self.assertEqual(cd.load_config(None)["date_format"], "{day} {month}")

    def test_desired_items_threads_date_format(self):
        cfg = cd.load_config(None, raw={"date_format": "{month} {day_english}"})
        contacts = [{"uid": "u", "fn": "Casey", "bday": "BDAY:1980-04-10",
                     "note": "", "categories": [], "labeled_dates": []}]
        items = cd.desired_items(contacts, dt.date(2026, 5, 30), cfg)
        blob = "".join(items.values())
        self.assertIn("on April 10th", blob)
        self.assertNotIn("on 10 April", blob)


class TestTrigger(unittest.TestCase):
    def test_table(self):
        self.assertEqual(cd.alarm_trigger(7, "11:30"), "-P6DT12H30M")
        self.assertEqual(cd.alarm_trigger(1, "11:30"), "-PT12H30M")
        self.assertEqual(cd.alarm_trigger(0, "11:30"), "PT11H30M")

    def test_days_only(self):
        self.assertEqual(cd.alarm_trigger(7, "00:00"), "-P7D")

    def test_zero(self):
        self.assertEqual(cd.alarm_trigger(0, "00:00"), "PT0S")


class TestIcs(unittest.TestCase):
    def test_escape_comma_semicolon(self):
        self.assertEqual(cd.ics_escape("a,b;c"), "a\\,b\\;c")

    def test_escape_newline(self):
        self.assertEqual(cd.ics_escape("a\nb"), "a\\nb")

    def test_escape_backslash(self):
        self.assertEqual(cd.ics_escape("a\\b"), "a\\\\b")

    def test_fold_75(self):
        folded = cd.fold_line("SUMMARY:" + "x" * 100)
        pieces = folded.split("\r\n")
        for piece in pieces:
            self.assertLessEqual(len(piece.encode("utf-8")), 75)
        self.assertEqual(pieces[1][0], " ")

    def test_fold_short_unchanged(self):
        self.assertEqual(cd.fold_line("SUMMARY:kort"), "SUMMARY:kort")


class TestBlacklistNote(unittest.TestCase):
    def test_marker_present(self):
        self.assertTrue(cd.note_blacklisted("blah #NB blah", "#NB"))

    def test_marker_at_end(self):
        self.assertTrue(cd.note_blacklisted("niet belangrijk #NB", "#NB"))

    def test_marker_absent(self):
        self.assertFalse(cd.note_blacklisted("gewoon een notitie", "#NB"))

    def test_case_insensitive(self):
        self.assertTrue(cd.note_blacklisted("klein #nb", "#NB"))

    def test_no_false_positive_substring(self):
        self.assertFalse(cd.note_blacklisted("ik hou van #NBA", "#NB"))

    def test_none_or_empty(self):
        self.assertFalse(cd.note_blacklisted(None, "#NB"))
        self.assertFalse(cd.note_blacklisted("", "#NB"))


# --- occurrence window + event building --------------------------

class TestOccurrences(unittest.TestCase):
    TODAY = dt.date(2026, 5, 30)

    def test_keep_past_includes_passed_birthday(self):
        occ = cd.occurrences_known(self.TODAY, 3, 19, 1971,
                                   future_days=730, past_days=365)
        self.assertEqual([d.year for d, _ in occ], [2026, 2027, 2028])
        self.assertEqual(occ[0], (dt.date(2026, 3, 19), 55))

    def test_no_past_when_keep_zero(self):
        occ = cd.occurrences_known(self.TODAY, 3, 19, 1971,
                                   future_days=730, past_days=0)
        self.assertEqual([d.year for d, _ in occ], [2027, 2028])
        self.assertEqual(occ[0], (dt.date(2027, 3, 19), 56))

    def test_age_is_turning_age_not_current(self):
        # born 2020-07-20, today 2026-05-30 (still 5) -> next = turns 6
        occ = cd.occurrences_known(self.TODAY, 7, 20, 2020,
                                   future_days=730, past_days=0)
        self.assertEqual(occ[0], (dt.date(2026, 7, 20), 6))

    def test_feb29_shifts_to_28_in_non_leap(self):
        occ = cd.occurrences_known(dt.date(2026, 1, 1), 2, 29, 2000,
                                   future_days=730, past_days=0)
        self.assertIn(dt.date(2026, 2, 28), [d for d, _ in occ])


# --- desired_items + reconcile + config --------------------------

class TestDesired(unittest.TestCase):
    TODAY = dt.date(2026, 5, 30)

    def _c(self, uid, fn, bday, note="", labeled_dates=None):
        return {"uid": uid, "fn": fn, "bday": bday, "categories": [],
                "note": note, "labeled_dates": labeled_dates or []}

    def test_skips_blacklisted_by_note(self):
        contacts = [self._c("u1", "X", "BDAY:1990-01-01",
                            note="oude collega #NB")]
        self.assertEqual(
            cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG), {})

    def test_skips_no_dates(self):
        contacts = [self._c("u1", "X", None)]
        self.assertEqual(
            cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG), {})

    def test_known_one_file_per_year(self):
        contacts = [self._c("u2", "Casey Example", "BDAY:1971-03-19")]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        self.assertEqual(sorted(items), [
            "auto-birthday-u2-2026-r0.ics",
            "auto-birthday-u2-2027-r0.ics",
            "auto-birthday-u2-2028-r0.ics",
        ])
        self.assertIn("BEGIN:VCALENDAR", items["auto-birthday-u2-2027-r0.ics"])
        self.assertIn("SUMMARY:🎂 Casey Example turns 56",
                      items["auto-birthday-u2-2027-r0.ics"])

    def test_unknown_single_file(self):
        contacts = [self._c("u3", "Casey Example",
                            "BDAY;X-APPLE-OMIT-YEAR=1604:1604-07-20")]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        self.assertEqual(list(items), ["auto-birthday-u3-r0.ics"])
        self.assertIn("RRULE:FREQ=YEARLY", items["auto-birthday-u3-r0.ics"])

    def test_birthday_and_anniversary_in_one_set(self):
        # A contact with BDAY *and* an Apple anniversary yields BOTH a
        # birthday and an anniversary event in the single collection.
        contacts = [self._c(
            "u5", "Casey Example", "BDAY:1980-04-10",
            labeled_dates=[{"date": "2002-10-26", "label": "Anniversary"}])]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        names = sorted(items)
        # birthday: 2026/2027/2028 (3) ; anniversary: 2026/2027/2028 (3)
        self.assertIn("auto-birthday-u5-2026-r0.ics", names)
        self.assertIn("auto-anniversary-u5-2026-r0.ics", names)
        self.assertIn("SUMMARY:🎂 Casey Example turns 46",
                      items["auto-birthday-u5-2026-r0.ics"])
        self.assertIn("SUMMARY:💍 Casey Example's 24th anniversary",
                      items["auto-anniversary-u5-2026-r0.ics"])
        self.assertEqual(
            len([n for n in names if n.startswith("auto-birthday-")]), 3)
        self.assertEqual(
            len([n for n in names if n.startswith("auto-anniversary-")]), 3)

    def test_standard_anniversary_no_bday(self):
        contacts = [self._c(
            "u6", "Dana Sample", None,
            labeled_dates=[{"date": "1999-06-15", "label": "Anniversary"}])]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        self.assertTrue(all(n.startswith("auto-anniversary-")
                            for n in items))
        self.assertTrue(items)

    def test_disabled_type_excluded(self):
        # other_dates is disabled by default -> custom label produces nothing.
        contacts = [self._c(
            "u7", "Erin Demo", None,
            labeled_dates=[{"date": "2015-09-01", "label": "Graduation"}])]
        self.assertEqual(
            cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG), {})

    def test_catch_all_claims_unclaimed_labels(self):
        raw = {"date_types": {"other_dates": {"enabled": True}}}
        cfg = cd.load_config(None, raw=raw)
        contacts = [self._c(
            "u8", "Erin Demo", None,
            labeled_dates=[
                {"date": "2002-10-26", "label": "Anniversary"},
                {"date": "2015-09-01", "label": "Graduation"}])]
        items = cd.desired_items(contacts, self.TODAY, cfg)
        # Anniversary handled by anniversary type; Graduation by other_dates.
        self.assertTrue(
            any(n.startswith("auto-anniversary-u8-") for n in items))
        self.assertTrue(
            any(n.startswith("auto-other_dates-u8-") for n in items))
        # no anniversary leaked into other_dates
        for n in items:
            if n.startswith("auto-other_dates-"):
                self.assertIn("Graduation", items[n])
                self.assertNotIn("anniversary", items[n].lower())

    def test_perpetual_anniversary_no_year(self):
        contacts = [self._c(
            "u9", "Fin Example", None,
            labeled_dates=[{"date": "--10-26", "label": "Anniversary"}])]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        self.assertEqual(list(items), ["auto-anniversary-u9-r0.ics"])
        self.assertIn("RRULE:FREQ=YEARLY",
                      items["auto-anniversary-u9-r0.ics"])

    def test_prodid_in_output(self):
        contacts = [self._c("u", "X", "BDAY:1980-04-10")]
        items = cd.desired_items(contacts, self.TODAY, cd.DEFAULT_CONFIG)
        self.assertIn("PRODID:-//radicale-contact-dates//EN",
                      list(items.values())[0])


class TestRemindersModel(unittest.TestCase):
    TODAY = dt.date(2026, 5, 30)

    def _c(self, uid, fn, bday, note="", labeled_dates=None):
        return {"uid": uid, "fn": fn, "bday": bday, "categories": [],
                "note": note, "labeled_dates": labeled_dates or []}

    def _bd_cfg(self, reminders):
        return cd.load_config(
            None, raw={"date_types": {"birthday": {"reminders": reminders}}})

    EVENT0 = {"days_before": 0, "at": "11:30", "type": "event",
              "template": "🎂 {name} turns {count}",
              "template_unknown": "🎂 {name}'s birthday"}
    ALARM7 = {"days_before": 7, "at": "11:30", "type": "alarm",
              "template": "🎂 {name} turns {count} on {date}",
              "template_unknown": "🎂 {name}'s birthday on {date}"}
    ALARM1 = {"days_before": 1, "at": "11:30", "type": "alarm",
              "template": "🎂 {name} turns {count} tomorrow",
              "template_unknown": "🎂 {name}'s birthday tomorrow"}

    def test_validate_requires_event(self):
        cfg = self._bd_cfg([self.ALARM7])
        with self.assertRaises(ValueError):
            cd.validate_config(cfg)

    def test_validate_ok_with_event(self):
        cd.validate_config(cd.load_config(None))  # defaults: no raise

    def test_dayof_event_hosts_alarms(self):
        cfg = self._bd_cfg([self.EVENT0, self.ALARM7, self.ALARM1])
        items = cd.desired_items([self._c("u", "Casey", "BDAY:1980-07-20")],
                                 self.TODAY, cfg)
        f = items["auto-birthday-u-2026-r0.ics"]
        self.assertIn("DTSTART;VALUE=DATE:20260720", f)
        self.assertIn("SUMMARY:🎂 Casey turns 46", f)
        self.assertIn("DESCRIPTION:🎂 Casey turns 46", f)
        self.assertEqual(f.count("BEGIN:VALARM"), 3)   # own popup + 7d + 1d
        self.assertIn("TRIGGER:PT11H30M", f)           # day-of popup
        self.assertIn("TRIGGER:-P6DT12H30M", f)        # 7 days before
        self.assertIn("TRIGGER:-PT12H30M", f)          # 1 day before
        self.assertIn("DESCRIPTION:🎂 Casey turns 46 on 20 July", f)
        self.assertIn("DESCRIPTION:🎂 Casey turns 46 tomorrow", f)

    def test_advance_event_pruned_when_past_dayof_kept(self):
        cfg = self._bd_cfg([
            self.EVENT0,
            {"days_before": 7, "at": "11:30", "type": "event",
             "template": "B7 {count} {date}", "template_unknown": "B7 {date}"},
        ])
        items = cd.desired_items([self._c("u", "Casey", "BDAY:1971-03-19")],
                                 self.TODAY, cfg)
        self.assertIn("auto-birthday-u-2026-r0.ics", items)        # day-of kept
        self.assertNotIn("auto-birthday-u-2026-r1.ics", items)     # advance gone
        self.assertIn("auto-birthday-u-2027-r1.ics", items)        # future kept

    def test_perpetual_recurs_yearly(self):
        cfg = self._bd_cfg([self.EVENT0, self.ALARM7])
        items = cd.desired_items(
            [self._c("u", "Casey", "BDAY;X-APPLE-OMIT-YEAR=1604:1604-07-20")],
            self.TODAY, cfg)
        self.assertEqual(list(items), ["auto-birthday-u-r0.ics"])
        f = items["auto-birthday-u-r0.ics"]
        self.assertIn("RRULE:FREQ=YEARLY", f)
        self.assertIn("SUMMARY:🎂 Casey's birthday", f)
        self.assertIn("DESCRIPTION:🎂 Casey's birthday on 20 July", f)

    def test_alarm_hosted_on_closest_to_zero_event(self):
        cfg = self._bd_cfg([
            {"days_before": 3, "at": "11:30", "type": "event",
             "template": "E {count}", "template_unknown": "E"},
            {"days_before": 10, "at": "09:00", "type": "alarm",
             "template": "A {count} {date}", "template_unknown": "A {date}"},
        ])
        items = cd.desired_items([self._c("u", "Casey", "BDAY:1980-07-20")],
                                 self.TODAY, cfg)
        f = items["auto-birthday-u-2026-r0.ics"]
        self.assertIn("DTSTART;VALUE=DATE:20260717", f)   # 3 days before 07-20
        self.assertEqual(f.count("BEGIN:VALARM"), 2)      # own popup + alarm
        self.assertIn("TRIGGER:-P6DT15H", f)              # 10d-before vs host

    def test_default_config_birthday_filenames(self):
        cfg = cd.load_config(None)
        items = cd.desired_items([self._c("u", "Casey", "BDAY:1980-07-20")],
                                 self.TODAY, cfg)
        # one event reminder (day-of) -> one file per occurrence (2025/26/27)
        self.assertEqual(sorted(items), [
            "auto-birthday-u-2025-r0.ics",
            "auto-birthday-u-2026-r0.ics",
            "auto-birthday-u-2027-r0.ics",
        ])


class TestReconcile(unittest.TestCase):
    def test_diff(self):
        desired = {"a.ics": "X", "b.ics": "NEW"}
        existing = {"b.ics": "OLD", "c.ics": "Z"}
        creates, updates, deletes = cd.reconcile(desired, existing)
        self.assertEqual(creates, {"a.ics": "X"})
        self.assertEqual(updates, {"b.ics": "NEW"})
        self.assertEqual(deletes, ["c.ics"])

    def test_no_change_when_equal(self):
        same = {"a.ics": "X"}
        self.assertEqual(cd.reconcile(same, dict(same)), ({}, {}, []))

    def test_ignores_dtstamp_rev_noise(self):
        desired = {"a.ics": "SUMMARY:x\r\nDTSTAMP:20260101T000000Z\r\n"}
        existing = {"a.ics": "SUMMARY:x\r\nDTSTAMP:20990101T000000Z\r\n"}
        self.assertEqual(cd.reconcile(desired, existing), ({}, {}, []))

    def test_perpetual_removed_when_year_added(self):
        desired = {"auto-birthday-u3-2026.ics": "A",
                   "auto-birthday-u3-2027.ics": "B"}
        existing = {"auto-birthday-u3.ics": "OLD-RRULE"}
        creates, updates, deletes = cd.reconcile(desired, existing)
        self.assertEqual(deletes, ["auto-birthday-u3.ics"])
        self.assertEqual(
            set(creates),
            {"auto-birthday-u3-2026.ics", "auto-birthday-u3-2027.ics"})

    def test_dated_removed_when_year_cleared(self):
        desired = {"auto-birthday-u3.ics": "RRULE"}
        existing = {"auto-birthday-u3-2026.ics": "A",
                    "auto-birthday-u3-2027.ics": "B"}
        creates, updates, deletes = cd.reconcile(desired, existing)
        self.assertEqual(
            deletes,
            ["auto-birthday-u3-2026.ics", "auto-birthday-u3-2027.ics"])
        self.assertEqual(set(creates), {"auto-birthday-u3.ics"})


class TestConfig(unittest.TestCase):
    def test_defaults_present(self):
        cfg = cd.load_config(None)
        self.assertEqual(cfg["future_days"], 730)
        self.assertEqual(cfg["past_days"], 365)
        self.assertIn("*/contacts", cfg["collections"])

    def test_global_suffix_prefix_prodid(self):
        cfg = cd.load_config(None)
        self.assertEqual(cfg["suffix"], "-auto-contact-dates")
        self.assertEqual(cfg["displayname_prefix"], "Contact dates")
        self.assertEqual(cfg["prodid"], "-//radicale-contact-dates//EN")

    def test_date_types_keys(self):
        cfg = cd.load_config(None)
        self.assertIn("date_types", cfg)
        for k in ("birthday", "anniversary", "other_dates"):
            self.assertIn(k, cfg["date_types"])

    def test_birthday_anniversary_enabled_other_disabled(self):
        dt_ = cd.load_config(None)["date_types"]
        self.assertTrue(dt_["birthday"]["enabled"])
        self.assertTrue(dt_["anniversary"]["enabled"])
        self.assertFalse(dt_["other_dates"]["enabled"])

    def test_birthday_source_and_category(self):
        bd = cd.load_config(None)["date_types"]["birthday"]
        self.assertEqual(bd["source"], "BDAY")
        self.assertEqual(bd["category"], "Birthday")
        reminders = bd["reminders"]
        self.assertTrue(any(r["type"] == "event" for r in reminders))
        self.assertIn("template", reminders[0])
        self.assertIn("template_unknown", reminders[0])

    def test_anniversary_apple_label_and_match(self):
        an = cd.load_config(None)["date_types"]["anniversary"]
        self.assertEqual(an["source"], "ANNIVERSARY")
        self.assertEqual(an["apple_label"], "Anniversary")
        self.assertEqual(an["category"], "Anniversary")

    def test_other_dates_catch_all_match(self):
        od = cd.load_config(None)["date_types"]["other_dates"]
        self.assertEqual(od["match"], "x-abdate-any")

    def test_merge_override_keeps_defaults(self):
        cfg = cd.load_config(None, raw={"future_days": 999})
        self.assertEqual(cfg["future_days"], 999)
        self.assertIn("reminders", cfg["date_types"]["birthday"])


# --- filesystem layer (tmpdir) -----------------------------------

class TestFs(unittest.TestCase):
    def test_write_and_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            coll = os.path.join(d, "x-auto-contact-dates")
            cd.ensure_collection(coll, "Contact dates (Test)")
            props = os.path.join(coll, ".Radicale.props")
            self.assertTrue(os.path.exists(props))
            with open(props, encoding="utf-8") as fh:
                meta = json.load(fh)
            self.assertEqual(meta["tag"], "VCALENDAR")
            self.assertEqual(meta["C:supported-calendar-component-set"], "VEVENT")
            cd.write_atomic(os.path.join(coll, "auto-birthday-u1.ics"),
                            "BEGIN\r\nEND\r\n")
            cd.write_atomic(os.path.join(coll, "auto-anniversary-u1.ics"),
                            "BEGIN\r\nEND\r\n")
            existing = cd.read_existing(coll)
            self.assertEqual(existing, {
                "auto-birthday-u1.ics": "BEGIN\r\nEND\r\n",
                "auto-anniversary-u1.ics": "BEGIN\r\nEND\r\n"})

    def test_read_ignores_unmanaged_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cd.write_atomic(os.path.join(d, "other.ics"), "Z")
            self.assertEqual(cd.read_existing(d), {})
            self.assertEqual(cd.read_existing(os.path.join(d, "nope")), {})

    def test_invalidate_cache_removes_dir(self):
        with tempfile.TemporaryDirectory() as d:
            cache = os.path.join(d, ".Radicale.cache")
            os.makedirs(cache)
            cd.invalidate_cache(d)
            self.assertFalse(os.path.exists(cache))


# --- Wildcard collections + discovery ------------------------------------

class TestDiscovery(unittest.TestCase):
    def test_discovers_addressbooks_by_vcf_and_props(self):
        with tempfile.TemporaryDirectory() as d:
            # alice/contacts: addressbook via VADDRESSBOOK props
            os.makedirs(os.path.join(d, "alice", "contacts"))
            cd.write_atomic(
                os.path.join(d, "alice", "contacts", ".Radicale.props"),
                json.dumps({"tag": "VADDRESSBOOK"}))
            # bob/contacts: detected by .vcf (no props)
            os.makedirs(os.path.join(d, "bob", "contacts"))
            cd.write_atomic(os.path.join(d, "bob", "contacts", "x.vcf"),
                            "BEGIN:VCARD\r\nEND:VCARD\r\n")
            # alice/calendar: VCALENDAR -> not an addressbook
            os.makedirs(os.path.join(d, "alice", "calendar"))
            cd.write_atomic(
                os.path.join(d, "alice", "calendar", ".Radicale.props"),
                json.dumps({"tag": "VCALENDAR"}))
            # existing -auto-contact-dates -> exclude
            os.makedirs(os.path.join(d, "bob", "contacts-auto-contact-dates"))
            found = cd.discover_addressbooks(d)
            self.assertEqual(found, ["alice/contacts", "bob/contacts"])

    def test_collection_settings_wildcard(self):
        collections = {"*/contacts": {"enabled": True},
                       "*/archived-contacts": {"enabled": False}}
        self.assertEqual(
            cd._collection_settings("alice/contacts", collections),
            {"enabled": True})
        self.assertEqual(
            cd._collection_settings("alice/archived-contacts", collections),
            {"enabled": False})
        self.assertIsNone(
            cd._collection_settings("alice/calendar", collections))


# --- sync/main integration (local fake tree from synthetic fixtures) --

class TestSyncIntegration(unittest.TestCase):
    TODAY = dt.date(2026, 5, 30)
    KNOWN = "synthetic-01.vcf"      # 1980-04-10 (known year)
    OMIT_YEAR = "synthetic-03.vcf"  # omit-year 07-20 (perpetual)
    BOTH = "synthetic-13.vcf"       # BDAY 1985-04-10 + Apple anniversary
    SUFFIX = "-auto-contact-dates"

    def _make_tree(self, d, files=None):
        ab = os.path.join(d, "fs", "contacts")
        os.makedirs(ab)
        for fn in (files or (self.KNOWN, self.OMIT_YEAR)):
            with open(os.path.join(FIXTURES, fn), encoding="utf-8",
                      errors="replace", newline="") as fh:
                data = fh.read()
            cd.write_atomic(os.path.join(ab, fn), data)
        return ab

    def _dir(self, d):
        return os.path.join(d, "fs", "contacts" + self.SUFFIX)

    def _cfg(self):
        return cd.load_config(
            None, raw={"collections": {"fs/contacts": {"enabled": True}}})

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_tree(d)
            summary = cd.sync(d, self._cfg(), self.TODAY, dry_run=True)
            self.assertGreater(summary["create"], 0)
            self.assertFalse(os.path.exists(self._dir(d)))

    def test_real_run_creates_then_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_tree(d)
            cfg = self._cfg()
            cd.sync(d, cfg, self.TODAY, dry_run=False)
            cdates_dir = self._dir(d)
            files = sorted(os.listdir(cdates_dir))
            ics = [f for f in files if f.endswith(".ics")]
            # synthetic-01: 2026/2027/2028 (3) + synthetic-03: perpetual (1) = 4
            self.assertEqual(len(ics), 4)
            self.assertIn(".Radicale.props", files)
            s2 = cd.sync(d, cfg, self.TODAY, dry_run=False)
            self.assertEqual(
                (s2["create"], s2["update"], s2["delete"]), (0, 0, 0))

    def test_birthday_and_anniversary_one_calendar(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_tree(d, files=(self.BOTH,))
            cfg = self._cfg()
            cd.sync(d, cfg, self.TODAY, dry_run=False)
            cdates_dir = self._dir(d)
            ics = sorted(f for f in os.listdir(cdates_dir)
                         if f.endswith(".ics"))
            bdays = [f for f in ics if f.startswith("auto-birthday-")]
            annis = [f for f in ics if f.startswith("auto-anniversary-")]
            # both types share the single calendar
            self.assertEqual(len(bdays), 3)
            self.assertEqual(len(annis), 3)
            blob = ""
            for f in ics:
                with open(os.path.join(cdates_dir, f), encoding="utf-8") as fh:
                    blob += fh.read()
            self.assertIn("CATEGORIES:Birthday", blob)
            self.assertIn("CATEGORIES:Anniversary", blob)

    def test_blacklist_removes_both_types(self):
        with tempfile.TemporaryDirectory() as d:
            ab = self._make_tree(d, files=(self.BOTH,))
            cfg = self._cfg()
            cd.sync(d, cfg, self.TODAY, dry_run=False)
            both = os.path.join(ab, self.BOTH)
            with open(both, encoding="utf-8", newline="") as fh:
                data = fh.read()
            data = data.replace("END:VCARD", "NOTE:keep out #NB\r\nEND:VCARD")
            cd.write_atomic(both, data)
            s = cd.sync(d, cfg, self.TODAY, dry_run=False)
            # 3 birthday + 3 anniversary items removed
            self.assertEqual(s["delete"], 6)
            ics = [f for f in os.listdir(self._dir(d)) if f.endswith(".ics")]
            self.assertEqual(ics, [])

    def test_blacklist_deletes_on_next_run(self):
        with tempfile.TemporaryDirectory() as d:
            ab = self._make_tree(d)
            cfg = self._cfg()
            cd.sync(d, cfg, self.TODAY, dry_run=False)
            omit_year = os.path.join(ab, self.OMIT_YEAR)
            with open(omit_year, encoding="utf-8", newline="") as fh:
                data = fh.read()
            data = data.replace(
                "END:VCARD", "NOTE:keep out #NB\r\nEND:VCARD")
            cd.write_atomic(omit_year, data)
            s = cd.sync(d, cfg, self.TODAY, dry_run=False)
            self.assertEqual(s["delete"], 1)
            perpetual = os.path.join(
                self._dir(d), "auto-birthday-%s-r0.ics" % self.OMIT_YEAR[:-4])
            self.assertFalse(os.path.exists(perpetual))

    def test_reminders_roundtrip_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_tree(d, files=(self.KNOWN,))
            cfg = self._cfg()  # default: day-of event hosting 7d/1d alarms
            cd.sync(d, cfg, self.TODAY, dry_run=False)
            ics = sorted(f for f in os.listdir(self._dir(d))
                         if f.endswith(".ics"))
            # known birthday: 3 occurrences -> 3 event files
            self.assertEqual(len(ics), 3)
            with open(os.path.join(self._dir(d), ics[0]),
                      encoding="utf-8") as h:
                blob = h.read()
            # own popup + 7d alarm + 1d alarm, all hosted on the day-of event
            self.assertEqual(blob.count("BEGIN:VALARM"), 3)
            s2 = cd.sync(d, cfg, self.TODAY, dry_run=False)
            self.assertEqual(
                (s2["create"], s2["update"], s2["delete"]), (0, 0, 0))

    def test_main_dry_run_smoke(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_tree(d)
            rc = cd.main(["--root", d, "--collection", "fs/contacts",
                          "--dry-run"])
            self.assertEqual(rc, 0)
            self.assertFalse(os.path.exists(self._dir(d)))


class TestDisplayname(unittest.TestCase):
    def test_prefix_default_english(self):
        with tempfile.TemporaryDirectory() as d:
            ab = os.path.join(d, "x", "contacts")
            os.makedirs(ab)
            cd.write_atomic(os.path.join(ab, ".Radicale.props"),
                            json.dumps({"D:displayname": "Contacts (Team)"}))
            self.assertEqual(
                cd.contact_dates_displayname(ab, "x/contacts", "Contact dates"),
                "Contact dates (Team)")

    def test_from_source_props_person(self):
        with tempfile.TemporaryDirectory() as d:
            ab = os.path.join(d, "alice", "contacts")
            os.makedirs(ab)
            cd.write_atomic(os.path.join(ab, ".Radicale.props"), json.dumps(
                {"tag": "VADDRESSBOOK", "D:displayname": "Contacts (Alice)"}))
            self.assertEqual(
                cd.contact_dates_displayname(
                    ab, "alice/contacts", "Contact dates"),
                "Contact dates (Alice)")

    def test_shared_uppercase_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            ab = os.path.join(d, "hq", "contacts")
            os.makedirs(ab)
            cd.write_atomic(os.path.join(ab, ".Radicale.props"),
                            json.dumps({"D:displayname": "Contacts (HQ)"}))
            self.assertEqual(
                cd.contact_dates_displayname(ab, "hq/contacts", "Contact dates"),
                "Contact dates (HQ)")

    def test_fallback_without_props(self):
        with tempfile.TemporaryDirectory() as d:
            ab = os.path.join(d, "bob", "contacts")
            os.makedirs(ab)
            self.assertEqual(
                cd.contact_dates_displayname(
                    ab, "bob/contacts", "Contact dates"),
                "Contact dates (bob)")


# --- Synthetic fixtures --------------------------------------------------

class TestSyntheticFixtures(unittest.TestCase):
    def test_parses_all_synthetic_vcards(self):
        files = [f for f in os.listdir(FIXTURES) if f.endswith(".vcf")]
        self.assertGreaterEqual(len(files), 10)
        for fn in files:
            with open(os.path.join(FIXTURES, fn), encoding="utf-8",
                      errors="replace") as fh:
                c = cd.parse_vcard(fh.read())
            self.assertTrue(c["uid"], "%s missing UID" % fn)
            res = cd.parse_date(c["bday"]) if c["bday"] else None
            self.assertTrue(res is None or len(res) == 3,
                            "%s bday not 3-tuple/None" % fn)

    def test_known_contact_synthetic_01(self):
        path = os.path.join(FIXTURES, "synthetic-01.vcf")
        with open(path, encoding="utf-8") as fh:
            c = cd.parse_vcard(fh.read())
        self.assertEqual(c["fn"], "Alpha Testperson")
        self.assertEqual(cd.parse_date(c["bday"]), (4, 10, 1980))


if __name__ == "__main__":
    unittest.main()

"""Absagen: Ausfälle aus Airtable und ihre Darstellung in der iCal-Datei."""
import contextlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from hilfen import ausfall, build, lade_cfg, termin, zeit

CFG = lade_cfg()
SLUG = CFG["verein"]["slug"]
STEMPEL = "20260101T000000Z"
# Dienstags ab 03.03.2026
SERIE = dict(start=zeit(2026, 3, 3), wiederholung="FREQ=WEEKLY;UNTIL=20260630T215959Z")


def ereignisse(t) -> list[list[str]]:
    """Die VEVENT-Blöcke eines Termins als Listen von Zeilen."""
    bloecke, block = [], []
    for z in build.vevent(t, SLUG, "Europe/Berlin", STEMPEL):
        block.append(z)
        if z == "END:VEVENT":
            bloecke.append(block)
            block = []
    return bloecke


class Ausfaelle(unittest.TestCase):
    def test_ausfall_fuer_eine_mannschaft(self):
        u17 = termin(id="recU17", mannschaft="U17", **SERIE)
        u9 = termin(id="recU9", mannschaft="U9", **SERIE)
        n = build.wende_ausfaelle_an([u17, u9], [ausfall("2026-03-10", mannschaft="U17", grund="Platz gesperrt")], CFG)
        self.assertEqual(n, 1)
        self.assertEqual(u17.absagen, {date(2026, 3, 10): "Platz gesperrt"})
        self.assertEqual(u9.absagen, {})

    def test_ausfall_fuer_einen_verknuepften_termin(self):
        a = termin(id="recA", mannschaft="U17", **SERIE)
        b = termin(id="recB", mannschaft="U17", **SERIE)
        build.wende_ausfaelle_an([a, b], [ausfall("2026-03-10", termin_ids=["recA"])], CFG)
        self.assertEqual(list(a.absagen), [date(2026, 3, 10)])
        self.assertEqual(b.absagen, {})

    def test_zeitraum_gilt_einschliesslich_letztem_tag(self):
        t = termin(mannschaft="U17", **SERIE)
        n = build.wende_ausfaelle_an([t], [ausfall("2026-03-10", bis="2026-03-24", mannschaft="U17")], CFG)
        self.assertEqual(n, 3)
        self.assertEqual(sorted(t.absagen), [date(2026, 3, 10), date(2026, 3, 17), date(2026, 3, 24)])

    def test_tag_ohne_termin_trifft_nichts(self):
        t = termin(mannschaft="U17", **SERIE)
        self.assertEqual(build.wende_ausfaelle_an([t], [ausfall("2026-03-11", mannschaft="U17")], CFG), 0)
        self.assertEqual(t.absagen, {})

    def test_mannschaft_trifft_nur_trainings(self):
        training = termin(id="recT", mannschaft="U9", start=zeit(2026, 3, 14, 9))
        turnier = termin(id="recE", mannschaft="U9", kategorie="Turnier", start=zeit(2026, 3, 14, 10))
        abend = termin(id="recV", mannschaft="U9", kategorie="Veranstaltung", start=zeit(2026, 3, 14, 19))
        n = build.wende_ausfaelle_an([training, turnier, abend], [ausfall("2026-03-14", mannschaft="U9")], CFG)
        self.assertEqual(n, 1)
        self.assertEqual(list(training.absagen), [date(2026, 3, 14)])
        self.assertEqual(turnier.absagen, {})
        self.assertEqual(abend.absagen, {})

    def test_kategorien_kommen_aus_der_konfiguration(self):
        kurs = termin(mannschaft="U9", kategorie="Kurs", **SERIE)
        cfg = {"feiertage": {"kategorien": ["Training", "Kurs"]}}
        self.assertEqual(build.wende_ausfaelle_an([kurs], [ausfall("2026-03-10", mannschaft="U9")], cfg), 1)

    def test_verknuepfter_termin_jede_kategorie(self):
        turnier = termin(id="recE", mannschaft="U9", kategorie="Turnier", start=zeit(2026, 3, 14, 10))
        build.wende_ausfaelle_an([turnier], [ausfall("2026-03-14", termin_ids=["recE"], grund="Krankheit")], CFG)
        self.assertEqual(turnier.absagen, {date(2026, 3, 14): "Krankheit"})

    def test_abteilung_im_ausfall_grenzt_ein(self):
        fussball = termin(id="recF", mannschaft="U9", **SERIE)
        handball = termin(id="recH", mannschaft="U9", abteilung="Handball", **SERIE)
        eintrag = ausfall("2026-03-10", mannschaft="U9")
        eintrag["fields"]["Abteilung"] = "Handball"
        self.assertEqual(build.wende_ausfaelle_an([fussball, handball], [eintrag], CFG), 1)
        self.assertEqual(fussball.absagen, {})
        self.assertEqual(list(handball.absagen), [date(2026, 3, 10)])

    def test_ohne_abteilung_und_eindeutig_keine_warnung(self):
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            build.wende_ausfaelle_an([termin(mannschaft="U9", **SERIE)], [ausfall("2026-03-10", mannschaft="U9")], CFG)
        self.assertEqual(log.getvalue(), "")

    def test_ohne_abteilung_und_mehrdeutig_warnt(self):
        fussball = termin(id="recF", mannschaft="U9", **SERIE)
        handball = termin(id="recH", mannschaft="U9", abteilung="Handball", **SERIE)
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            n = build.wende_ausfaelle_an([fussball, handball], [ausfall("2026-03-10", mannschaft="U9")], CFG)
        self.assertEqual(n, 2)                       # wie bisher: beide, aber nicht mehr stillschweigend
        self.assertIn("U9", log.getvalue())
        self.assertIn("Fußball", log.getvalue())
        self.assertIn("Handball", log.getvalue())

    def test_bfv_spiele_sind_ausgenommen(self):
        spiel = termin(id="bfv-123", mannschaft="U17", kategorie="Spiel", start=zeit(2026, 3, 10, 11))
        self.assertEqual(build.wende_ausfaelle_an([spiel], [ausfall("2026-03-10", mannschaft="U17")], CFG), 0)
        self.assertEqual(spiel.absagen, {})

    def test_ausfall_ohne_datum_wird_uebersprungen(self):
        t = termin(mannschaft="U17", **SERIE)
        self.assertEqual(build.wende_ausfaelle_an([t], [{"id": "recX", "fields": {"Mannschaft": "U17"}}], CFG), 0)

    def test_ausfall_ohne_mannschaft_und_termin_trifft_nichts(self):
        t = termin(mannschaft="", **SERIE)
        self.assertEqual(build.wende_ausfaelle_an([t], [ausfall("2026-03-10")], CFG), 0)

    def test_ausfall_ersetzt_den_feiertagsgrund(self):
        # Reihenfolge wie im Build: erst Feiertage, dann Ausfälle
        t = termin(mannschaft="U17", start=zeit(2026, 12, 3), wiederholung="FREQ=WEEKLY;UNTIL=20261231T225959Z")
        build.wende_feiertage_an([t], CFG)
        build.wende_ausfaelle_an([t], [ausfall("2026-12-24", mannschaft="U17", grund="Winterpause")], CFG)
        self.assertEqual(t.absagen[date(2026, 12, 24)], "Winterpause")
        self.assertEqual(t.absagen[date(2026, 12, 31)], "Feiertag (Silvester)")


class ICal(unittest.TestCase):
    def test_termin_ohne_absage(self):
        (e,) = ereignisse(termin(id="recA", titel="Training U17", **SERIE))
        self.assertIn(f"UID:recA@{SLUG}", e)
        self.assertIn("SUMMARY:Training U17", e)
        self.assertNotIn("STATUS:CANCELLED", e)

    def test_abgesagter_tag_einer_serie(self):
        t = termin(id="recA", titel="Training U17", ort="Vereinsgelände", beschreibung="Bitte pünktlich", **SERIE)
        t.absagen[date(2026, 3, 10)] = "Platz gesperrt"
        serie, absage = ereignisse(t)
        # Die Serie selbst bleibt unverändert
        self.assertIn("RRULE:FREQ=WEEKLY;UNTIL=20260630T215959Z", serie)
        self.assertNotIn("STATUS:CANCELLED", serie)
        self.assertFalse([z for z in serie if z.startswith("EXDATE")])
        # Der abgesagte Tag ist eine Ausnahme mit derselben UID
        self.assertIn(f"UID:recA@{SLUG}", absage)
        self.assertIn("RECURRENCE-ID;TZID=Europe/Berlin:20260310T180000", absage)
        self.assertIn("DTSTART;TZID=Europe/Berlin:20260310T180000", absage)
        self.assertIn("DTEND;TZID=Europe/Berlin:20260310T193000", absage)
        self.assertIn("STATUS:CANCELLED", absage)
        self.assertIn("TRANSP:TRANSPARENT", absage)
        self.assertIn("SUMMARY:Training U17", absage)   # kein „Abgesagt:“ im Titel
        self.assertIn("DESCRIPTION:Fällt aus: Platz gesperrt\\n\\nBitte pünktlich", absage)
        self.assertIn("LOCATION:Vereinsgelände", absage)
        self.assertFalse([z for z in absage if z.startswith("RRULE")])

    def test_mehrere_absagen_je_eine_ausnahme(self):
        t = termin(**SERIE)
        t.absagen = {date(2026, 3, 17): "", date(2026, 3, 10): ""}
        _, a, b = ereignisse(t)
        self.assertIn("RECURRENCE-ID;TZID=Europe/Berlin:20260310T180000", a)
        self.assertIn("RECURRENCE-ID;TZID=Europe/Berlin:20260317T180000", b)
        self.assertIn("DESCRIPTION:Fällt aus.", a)

    def test_abgesagter_einzeltermin(self):
        t = termin(id="recE", titel="Turnier U9", start=zeit(2026, 3, 14, 10))
        t.absagen[date(2026, 3, 14)] = "Krankheit"
        (e,) = ereignisse(t)
        self.assertIn(f"UID:recE@{SLUG}", e)
        self.assertIn("STATUS:CANCELLED", e)
        self.assertIn("TRANSP:TRANSPARENT", e)
        self.assertIn("SUMMARY:Turnier U9", e)
        self.assertIn("DESCRIPTION:Fällt aus: Krankheit", e)
        self.assertFalse([z for z in e if z.startswith("RECURRENCE-ID")])

    def test_absage_ueber_die_zeitumstellung(self):
        # Serie beginnt in der Winterzeit, Absage liegt in der Sommerzeit: Uhrzeit bleibt 18:00
        t = termin(**SERIE)
        t.absagen[date(2026, 3, 31)] = ""
        _, absage = ereignisse(t)
        self.assertIn("RECURRENCE-ID;TZID=Europe/Berlin:20260331T180000", absage)

    def test_ganztaegige_serie(self):
        t = termin(start=date(2026, 3, 3), wiederholung="FREQ=WEEKLY")
        t.absagen[date(2026, 3, 10)] = ""
        _, absage = ereignisse(t)
        self.assertIn("RECURRENCE-ID;VALUE=DATE:20260310", absage)
        self.assertIn("DTEND;VALUE=DATE:20260311", absage)


class Datei(unittest.TestCase):
    """Die fertige .ics-Datei: Zeilenenden, Faltung, jeder Termin nur im passenden Kalender."""

    @classmethod
    def setUpClass(cls):
        lang = "Sehr langer Hinweis mit Umlauten äöü, Komma; Semikolon und Zeilenumbruch.\n" * 4
        t = termin(id="recA", titel="Training U17", mannschaft="U17", beschreibung=lang, **SERIE)
        t.absagen[date(2026, 3, 10)] = "Platz gesperrt"
        intern = termin(id="recI", titel="Sitzung", sichtbarkeit="intern", kategorie="Gremium")
        feed = build.Feed(id="x", name="Test – X", beschreibung="", zugang="oeffentlich",
                          sichtbarkeit=["oeffentlich"])
        with tempfile.TemporaryDirectory() as ordner:
            pfad = Path(ordner) / "x.ics"
            cls.anzahl = build.schreibe_ics(pfad, feed, [t, intern], CFG, STEMPEL)
            cls.roh = pfad.read_bytes()

    def test_nur_passende_termine(self):
        self.assertEqual(self.anzahl, 1)
        self.assertNotIn(b"recI", self.roh)
        self.assertNotIn(b"Sitzung", self.roh)

    def test_zeilenenden_crlf(self):
        self.assertTrue(self.roh.endswith(b"END:VCALENDAR\r\n"))
        self.assertEqual(self.roh.count(b"\n"), self.roh.count(b"\r\n"))

    def test_zeilen_hoechstens_75_byte(self):
        for zeile in self.roh.split(b"\r\n"):
            self.assertLessEqual(len(zeile), 75, zeile)

    def test_entfaltet_wieder_lesbar(self):
        zeilen = build.entfalte(self.roh.decode("utf-8"))
        self.assertEqual(zeilen.count(f"UID:recA@{SLUG}"), 2)   # Serie und abgesagter Tag
        self.assertEqual(zeilen.count("STATUS:CANCELLED"), 1)
        self.assertEqual(zeilen[0], "BEGIN:VCALENDAR")
        self.assertTrue(any(z.startswith("DESCRIPTION:Sehr langer Hinweis mit Umlauten äöü\\, Komma\\; "
                                         "Semikolon und Zeilenumbruch.\\n") for z in zeilen))


if __name__ == "__main__":
    unittest.main()

"""Feiertage: Trainingsserien werden an Feiertagen als abgesagt markiert."""
import unittest
from datetime import date

from hilfen import build, lade_cfg, termin, zeit

CFG = lade_cfg()
# Donnerstags ab 03.12.2026: trifft Heiligabend und Silvester 2026.
DONNERSTAGS = dict(start=zeit(2026, 12, 3), wiederholung="FREQ=WEEKLY;UNTIL=20270131T225959Z")


class Kalender(unittest.TestCase):
    def test_ostersonntag(self):
        self.assertEqual(build.ostersonntag(2024), date(2024, 3, 31))
        self.assertEqual(build.ostersonntag(2025), date(2025, 4, 20))
        self.assertEqual(build.ostersonntag(2026), date(2026, 4, 5))
        self.assertEqual(build.ostersonntag(2027), date(2027, 3, 28))

    def test_feiertage_bayern_2026(self):
        tage = build.feiertage(2026, {})
        self.assertEqual(sorted(tage), [
            date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 3), date(2026, 4, 6),
            date(2026, 5, 1), date(2026, 5, 14), date(2026, 5, 25), date(2026, 6, 4),
            date(2026, 8, 15), date(2026, 10, 3), date(2026, 11, 1), date(2026, 12, 25),
            date(2026, 12, 26)])
        self.assertEqual(tage[date(2026, 4, 3)], "Karfreitag")
        self.assertEqual(tage[date(2026, 6, 4)], "Fronleichnam")

    def test_heiligabend_und_silvester_aus_der_konfiguration(self):
        tage = build.feiertage(2026, CFG)
        self.assertEqual(tage[date(2026, 12, 24)], "Heiligabend")
        self.assertEqual(tage[date(2026, 12, 31)], "Silvester")


class Regel(unittest.TestCase):
    def test_trainingsserie_wird_am_feiertag_abgesagt(self):
        t = termin(**DONNERSTAGS)
        n = build.wende_feiertage_an([t], CFG)
        self.assertEqual(n, 2)
        self.assertEqual(t.absagen, {date(2026, 12, 24): "Feiertag (Heiligabend)",
                                     date(2026, 12, 31): "Feiertag (Silvester)"})

    def test_abgesagt_heisst_nicht_geloescht(self):
        t = termin(**DONNERSTAGS)
        build.wende_feiertage_an([t], CFG)
        tage = [s.date() for s in build.vorkommen(t, date(2026, 12, 1), date(2027, 1, 31))]
        self.assertIn(date(2026, 12, 24), tage)
        self.assertEqual(t.ausnahmen, set())

    def test_haekchen_auch_an_feiertagen(self):
        t = termin(auch_feiertags=True, **DONNERSTAGS)
        self.assertEqual(build.wende_feiertage_an([t], CFG), 0)
        self.assertEqual(t.absagen, {})

    def test_andere_kategorien_bleiben(self):
        t = termin(kategorie="Gremium", **DONNERSTAGS)
        self.assertEqual(build.wende_feiertage_an([t], CFG), 0)

    def test_einzeltermine_bleiben(self):
        t = termin(start=zeit(2026, 12, 24))
        self.assertEqual(build.wende_feiertage_an([t], CFG), 0)
        self.assertEqual(t.absagen, {})

    def test_bewegliche_feiertage(self):
        # Freitags ab 27.03.2026: Karfreitag (03.04.) und Tag der Arbeit (01.05.)
        t = termin(start=zeit(2026, 3, 27), wiederholung="FREQ=WEEKLY;UNTIL=20260531T215959Z")
        build.wende_feiertage_an([t], CFG)
        self.assertEqual(t.absagen, {date(2026, 4, 3): "Feiertag (Karfreitag)",
                                     date(2026, 5, 1): "Feiertag (Tag der Arbeit)"})

    def test_training_an_zwei_wochentagen(self):
        # Dienstags und donnerstags: nur der Donnerstag fällt auf Heiligabend
        t = termin(start=zeit(2026, 12, 1), wiederholung="FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20261227T225959Z")
        build.wende_feiertage_an([t], CFG)
        self.assertEqual(list(t.absagen), [date(2026, 12, 24)])

    def test_serie_endet_vor_dem_feiertag(self):
        t = termin(start=zeit(2026, 12, 3), wiederholung="FREQ=WEEKLY;UNTIL=20261220T225959Z")
        self.assertEqual(build.wende_feiertage_an([t], CFG), 0)

    def test_eigener_absagegrund_bleibt_stehen(self):
        t = termin(**DONNERSTAGS)
        t.absagen[date(2026, 12, 24)] = "Platz gesperrt"
        build.wende_feiertage_an([t], CFG)
        self.assertEqual(t.absagen[date(2026, 12, 24)], "Platz gesperrt")


if __name__ == "__main__":
    unittest.main()

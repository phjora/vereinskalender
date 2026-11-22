"""Einlesen aus Airtable: aus einem Datensatz wird ein Termin (airtable_termin)."""
import contextlib
import io
import unittest
from datetime import date, timedelta

from hilfen import TZ, build


def datensatz(**felder) -> dict:
    basis = {"Titel": "Testtermin", "Beginn": "2026-03-03T17:00:00.000Z", "Sichtbarkeit": "Öffentlich"}
    return {"id": "recTest", "fields": {k: v for k, v in {**basis, **felder}.items() if v is not None}}


def lies(**felder):
    """Gibt (Termin oder None, Warnungen) zurück."""
    log = io.StringIO()
    with contextlib.redirect_stderr(log):
        t = build.airtable_termin(datensatz(**felder), TZ)
    return t, log.getvalue()


class Sichtbarkeit(unittest.TestCase):
    def test_die_vier_stufen(self):
        for wert, stufe in [("Öffentlich", "oeffentlich"), ("Trainer:innen", "trainer"),
                            ("Intern (Funktionäre)", "intern"), ("Vorstand", "vorstand")]:
            with self.subTest(wert):
                t, warnungen = lies(Sichtbarkeit=wert)
                self.assertEqual(t.sichtbarkeit, stufe)
                self.assertEqual(warnungen, "")

    def test_unbekannter_wert_wird_nicht_veroeffentlicht(self):
        t, warnungen = lies(Titel="Geheime Sitzung", Sichtbarkeit="Abteilungsleitung")
        self.assertIsNone(t)
        self.assertIn("recTest", warnungen)
        self.assertIn("Abteilungsleitung", warnungen)
        self.assertNotIn("Geheime Sitzung", warnungen)   # Titel gehört nicht ins öffentliche Log

    def test_fehlender_wert_wird_nicht_veroeffentlicht(self):
        t, warnungen = lies(Sichtbarkeit=None)
        self.assertIsNone(t)
        self.assertIn("recTest", warnungen)


class Felder(unittest.TestCase):
    def test_id_ist_die_record_id(self):
        self.assertEqual(lies()[0].id, "recTest")

    def test_uhrzeit_in_ortszeit(self):
        t, _ = lies(Beginn="2026-03-03T17:00:00.000Z", Ende="2026-03-03T19:00:00.000Z")
        self.assertEqual((t.start.hour, t.ende.hour), (18, 20))        # Winterzeit
        t, _ = lies(Beginn="2026-06-02T16:00:00.000Z")
        self.assertEqual(t.start.hour, 18)                             # Sommerzeit

    def test_ohne_ende_90_minuten(self):
        t, _ = lies()
        self.assertEqual(t.ende - t.start, timedelta(minutes=90))
        t, _ = lies(Ende="2026-03-03T16:00:00.000Z")                   # Ende vor Beginn
        self.assertEqual(t.ende - t.start, timedelta(minutes=90))

    def test_ganztaegig(self):
        t, _ = lies(**{"Ganztägig": True, "Beginn": "2026-03-07T08:00:00.000Z"})
        self.assertEqual((t.start, t.ende), (date(2026, 3, 7), date(2026, 3, 8)))

    def test_wiederholen_bis_gilt_einschliesslich(self):
        t, _ = lies(**{"Wiederholung": "Wöchentlich", "Wiederholen bis": "2026-03-17"})
        tage = [s.date() for s in build.vorkommen(t, date(2026, 3, 1), date(2026, 4, 30))]
        self.assertEqual(tage, [date(2026, 3, 3), date(2026, 3, 10), date(2026, 3, 17)])

    def test_einmalig_ist_keine_serie(self):
        self.assertEqual(lies(Wiederholung="Einmalig")[0].wiederholung, "")

    def test_ort_und_adresse_werden_zusammengefuehrt(self):
        self.assertEqual(lies(Ort="Sonstiges", Adresse="Musterweg 1")[0].ort, "Sonstiges, Musterweg 1")

    def test_zielgruppe_aus_mannschaft(self):
        self.assertEqual(lies(Mannschaft="U9")[0].zielgruppe, "Jugend")
        self.assertEqual(lies(Mannschaft="U9", Zielgruppe="Alle")[0].zielgruppe, "Jugend")
        self.assertEqual(lies()[0].zielgruppe, "Alle")                 # ohne Mannschaft, Feld leer

    def test_interne_felder_werden_nie_gelesen(self):
        t, _ = lies(**{"Notiz intern": "GEHEIM-NOTIZ", "Eingereicht von": "GEHEIM-NAME"})
        self.assertNotIn("GEHEIM", repr(t))

    def test_ohne_titel_oder_beginn_uebersprungen(self):
        self.assertIsNone(lies(Titel="")[0])
        self.assertIsNone(lies(Beginn=None)[0])


if __name__ == "__main__":
    unittest.main()

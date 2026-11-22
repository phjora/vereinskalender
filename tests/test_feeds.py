"""Welcher Termin landet in welchem Kalender? (Feed.passt)"""
import unittest

from hilfen import build, lade_feeds, termin


def feed(**kw) -> build.Feed:
    basis = dict(id="x", name="Test – X", beschreibung="", zugang="oeffentlich",
                 sichtbarkeit=["oeffentlich"])
    return build.Feed(**{**basis, **kw})


class Regeln(unittest.TestCase):
    """Die Filterregeln einzeln, in der Reihenfolge aus der README."""

    def test_ohne_einschraenkung_passt_alles_oeffentliche(self):
        self.assertTrue(feed().passt(termin()))

    def test_sichtbarkeit_muss_passen(self):
        f = feed()
        for stufe in ("trainer", "intern", "vorstand"):
            self.assertFalse(f.passt(termin(sichtbarkeit=stufe)), stufe)

    def test_sichtbarkeit_geht_vor_hauptverein(self):
        f = feed(inkl_hauptverein=True)
        self.assertFalse(f.passt(termin(abteilung="Hauptverein", kategorie="Veranstaltung",
                                        sichtbarkeit="intern")))

    def test_ohne_zielgruppen_schliesst_aus(self):
        f = feed(ohne_zielgruppen=["Erwachsene"])
        self.assertFalse(f.passt(termin(zielgruppe="Erwachsene")))
        self.assertTrue(f.passt(termin(zielgruppe="Jugend")))
        self.assertTrue(f.passt(termin(zielgruppe="")))

    def test_ohne_zielgruppen_geht_vor_hauptverein(self):
        f = feed(inkl_hauptverein=True, ohne_zielgruppen=["Erwachsene"])
        self.assertFalse(f.passt(termin(abteilung="Hauptverein", kategorie="Veranstaltung",
                                        zielgruppe="Erwachsene")))

    def test_hauptverein_kommt_dazu_ausser_gremium(self):
        f = feed(abteilungen=["Judo"], inkl_hauptverein=True)
        self.assertTrue(f.passt(termin(abteilung="Hauptverein", kategorie="Veranstaltung")))
        self.assertFalse(f.passt(termin(abteilung="Hauptverein", kategorie="Gremium")))
        self.assertFalse(feed(abteilungen=["Judo"]).passt(
            termin(abteilung="Hauptverein", kategorie="Veranstaltung")))

    def test_abteilungsweite_termine_kommen_dazu(self):
        f = feed(mannschaften=["U9"], inkl_abteilung=["Fußball"])
        self.assertTrue(f.passt(termin(kategorie="Veranstaltung")))                    # ohne Mannschaft
        self.assertFalse(f.passt(termin(kategorie="Veranstaltung", mannschaft="U17")))  # andere Mannschaft
        self.assertFalse(f.passt(termin(kategorie="Gremium")))
        self.assertFalse(f.passt(termin(kategorie="Veranstaltung", abteilung="Judo")))

    def test_abteilungen_grenzen_ein(self):
        f = feed(abteilungen=["Judo"])
        self.assertTrue(f.passt(termin(abteilung="Judo")))
        self.assertFalse(f.passt(termin(abteilung="Fußball")))

    def test_ohne_kategorien_schliesst_aus(self):
        f = feed(ohne_kategorien=["Training"])
        self.assertFalse(f.passt(termin(kategorie="Training")))
        self.assertTrue(f.passt(termin(kategorie="Spiel")))

    def test_bei_mehreren_bedingungen_reicht_ein_treffer(self):
        f = feed(kategorien=["Spiel"], mannschaften=["U9"])
        self.assertTrue(f.passt(termin(kategorie="Spiel", mannschaft="U17")))
        self.assertTrue(f.passt(termin(kategorie="Training", mannschaft="U9")))
        self.assertFalse(f.passt(termin(kategorie="Training", mannschaft="U17")))

    def test_zielgruppe_wird_aus_mannschaft_abgeleitet(self):
        self.assertEqual(build.zielgruppe_fuer("", "U9"), "Jugend")
        self.assertEqual(build.zielgruppe_fuer("", "Bambini"), "Jugend")
        self.assertEqual(build.zielgruppe_fuer("", "Herren"), "")
        self.assertEqual(build.zielgruppe_fuer("", ""), "")
        self.assertEqual(build.zielgruppe_fuer("Erwachsene", "U9"), "Erwachsene")  # Angabe geht vor

    def test_kombi_kalender_nimmt_was_in_einem_der_kalender_steht(self):
        k = build.KombiFeed([feed(id="a", abteilungen=["Judo"]), feed(id="b", abteilungen=["Turnen"])])
        self.assertEqual(k.id, "a_b")
        self.assertTrue(k.passt(termin(abteilung="Judo")))
        self.assertTrue(k.passt(termin(abteilung="Turnen")))
        self.assertFalse(k.passt(termin(abteilung="Fußball")))


# Erfundene Termine und die Kalender aus config/verein.toml, in denen sie stehen sollen.
ABTEILUNGSKALENDER = {"fussball", "judo", "turnen", "aikido", "karate", "tischtennis", "handball",
                      "basketball", "tennis", "fitness-gymnastik"}
ERWARTET = [
    ("Training U9",
     dict(kategorie="Training", mannschaft="U9"),
     {"alle", "fussball", "2018-1"}),
    ("Spiel U17",
     dict(kategorie="Spiel", mannschaft="U17"),
     {"alle", "fussball", "fussball-jugend", "2010-1"}),
    ("Turnier U9",
     dict(kategorie="Turnier", mannschaft="U9"),
     {"alle", "jugend", "fussball", "fussball-jugend", "2018-1"}),
    ("Feier der Fußballjugend (ohne Mannschaft)",
     dict(kategorie="Veranstaltung", zielgruppe="Jugend"),
     {"alle", "jugend", "fussball", "fussball-jugend", "2018-1", "2010-1"}),
    ("Fußball-Stammtisch für Erwachsene",
     dict(kategorie="Veranstaltung", zielgruppe="Erwachsene"),
     {"alle", "fussball"}),
    ("Vereinsfest",
     dict(abteilung="Hauptverein", kategorie="Veranstaltung"),
     {"alle", "hauptverein", "jugend", "fussball-jugend", "2018-1", "2010-1"} | ABTEILUNGSKALENDER),
    ("Mitgliederversammlung (öffentliches Gremium)",
     dict(abteilung="Hauptverein", kategorie="Gremium"),
     {"alle", "hauptverein"}),
    ("Gürtelprüfung Judo",
     dict(abteilung="Judo", kategorie="Prüfung"),
     {"alle", "judo"}),
    ("Trainersitzung",
     dict(kategorie="Gremium", sichtbarkeit="trainer"),
     {"trainer", "intern", "vorstand"}),
    ("Ausschusssitzung",
     dict(abteilung="Hauptverein", kategorie="Gremium", sichtbarkeit="intern"),
     {"intern", "vorstand"}),
    ("Vorstandssitzung",
     dict(abteilung="Hauptverein", kategorie="Gremium", sichtbarkeit="vorstand"),
     {"vorstand"}),
]


class EchteKonfiguration(unittest.TestCase):
    """Prüft die Kalender aus config/verein.toml, damit auch Änderungen dort auffallen."""

    @classmethod
    def setUpClass(cls):
        cls.feeds = lade_feeds()

    def test_termine_landen_in_den_richtigen_kalendern(self):
        for name, angaben, erwartet in ERWARTET:
            with self.subTest(name):
                t = termin(titel=name, **angaben)
                self.assertEqual({fid for fid, f in self.feeds.items() if f.passt(t)}, erwartet)

    def test_oeffentliche_kalender_enthalten_nur_oeffentliches(self):
        for fid, f in self.feeds.items():
            if f.zugang == "oeffentlich":
                with self.subTest(fid):
                    self.assertEqual(f.sichtbarkeit, ["oeffentlich"])

    def test_interne_bausteine_enthalten_nichts_oeffentliches(self):
        for fid in ("trainer", "intern", "vorstand"):
            with self.subTest(fid):
                self.assertEqual(self.feeds[fid].zugang, "intern")
                self.assertNotIn("oeffentlich", self.feeds[fid].sichtbarkeit)

    def test_kennungen_bleiben_stabil(self):
        """Feed-IDs sind die Dateinamen der Abos. Wer hier etwas ändert, bricht bestehende Abos."""
        self.assertEqual(set(self.feeds), {
            "alle", "hauptverein", "jugend", "fussball-jugend", "2018-1", "2010-1",
            "trainer", "intern", "vorstand"} | ABTEILUNGSKALENDER)


if __name__ == "__main__":
    unittest.main()

"""BFV-Feeds: Umwandlung externer Spiele in normale Termine."""
import contextlib
import io
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from hilfen import build

TZ = ZoneInfo("Europe/Berlin")


def block(*zeilen):
    return ["BEGIN:VEVENT", *zeilen, "END:VEVENT"]


class Feed:
    mannschaften = ["U9"]
    abteilungen = ["Fußball"]
    externe_feeds = ["https://example.invalid/bfv.ics"]


class BfvFeeds(unittest.TestCase):
    def lade(self, *bloecke):
        with mock.patch.object(build, "hole_extern", return_value=([], list(bloecke))), \
                contextlib.redirect_stdout(io.StringIO()):
            return build.externe_termine([Feed()], TZ)

    def test_spiel_wird_termin(self):
        t = self.lade(block("UID:abc", "DTSTART:20261121T083000Z", "DTEND:20261121T101500Z",
                            "SUMMARY:TSV Großhadern-SV Musterstadt\\, Kinderfestival"))
        self.assertEqual(len(t), 1)
        self.assertEqual(t[0].id, "bfv-abc")
        self.assertEqual(t[0].kategorie, "Spiel")
        self.assertEqual(t[0].mannschaft, "U9")

    def test_leerer_platzhalter_wird_uebersprungen(self):
        # So sieht der BFV-Feed aus, wenn keine Spiele anstehen
        t = self.lade(block("UID:leer", "DTSTART:19691206T112327", "DTEND:19691206T112327", "SUMMARY:"))
        self.assertEqual(t, [])

    def test_ohne_titel_wird_uebersprungen(self):
        t = self.lade(block("UID:x", "DTSTART:20261121T083000Z"))
        self.assertEqual(t, [])


if __name__ == "__main__":
    unittest.main()

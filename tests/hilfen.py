"""Gemeinsame Helfer für die Tests. Alle Termine hier sind erfunden."""
import sys
import tomllib
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "generator"))

import build  # noqa: E402  (der Generator, generator/build.py)

TZ = ZoneInfo("Europe/Berlin")


def lade_cfg() -> dict:
    return tomllib.loads((ROOT / "config" / "verein.toml").read_text(encoding="utf-8"))


def lade_feeds() -> dict:
    """Alle Kalender aus der echten Konfiguration, nach ID."""
    return {f["id"]: build.Feed(**f) for f in lade_cfg()["feed"]}


def zeit(jahr: int, monat: int, tag: int, stunde: int = 18, minute: int = 0) -> datetime:
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=TZ)


def termin(id: str = "t1", titel: str = "Testtermin", start=None, dauer_min: int = 90,
           wiederholung: str = "", ort: str = "", abteilung: str = "Fußball",
           kategorie: str = "Training", mannschaft: str = "", sichtbarkeit: str = "oeffentlich",
           beschreibung: str = "", zielgruppe: str = "", auch_feiertags: bool = False) -> build.Termin:
    """Ein Termin mit sinnvollen Vorgaben. Die Zielgruppe wird wie im Generator abgeleitet."""
    start = start or zeit(2026, 3, 3)
    ganz = isinstance(start, date) and not isinstance(start, datetime)
    ende = start + (timedelta(days=1) if ganz else timedelta(minutes=dauer_min))
    return build.Termin(
        id=id, titel=titel, start=start, ende=ende, ganztaegig=ganz, wiederholung=wiederholung,
        ort=ort, abteilung=abteilung, kategorie=kategorie, mannschaft=mannschaft,
        sichtbarkeit=sichtbarkeit, beschreibung=beschreibung, auch_feiertags=auch_feiertags,
        zielgruppe=build.zielgruppe_fuer(zielgruppe, mannschaft))


def ausfall(datum: str, bis: str = "", mannschaft: str = "", termin_ids=(), grund: str = "") -> dict:
    """Ein Datensatz der Tabelle „Ausfälle“, so wie ihn Airtable liefert."""
    felder = {"Datum": datum}
    if bis:
        felder["Bis"] = bis
    if mannschaft:
        felder["Mannschaft"] = mannschaft
    if termin_ids:
        felder["Termin"] = list(termin_ids)
    if grund:
        felder["Grund"] = grund
    return {"id": "recAusfall", "fields": felder}

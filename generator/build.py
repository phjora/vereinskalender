#!/usr/bin/env python3
"""Vereinskalender – Generator.

Liest config/verein.toml und data/termine.csv (plus optionale externe
iCal-Feeds, z. B. vom BFV) und erzeugt daraus:

  public/<feed>.ics                  öffentliche Kalender
  public/i/<token>/<feed>.ics        interne Kalender (persönliche geheime Links)
  public/index.html                  Website mit Abo-Buttons, QR-Codes, Terminliste
  build/intern-links.txt             Übersicht der internen Links (wird NICHT veröffentlicht)

Nur Python-Standardbibliothek, damit es überall ohne Installation läuft.

Interne Zugänge kommen aus der Umgebungsvariable VK_INTERN_TOKENS als JSON,
z. B. {"Max Muster": {"token": "k3f9...", "feeds": ["intern", "u9"]}} – pro Person entsteht
ein persönlicher Kalender public/i/<token>/kalender.ics mit allem Gewählten.
Ohne Variable wird ein Demo-Zugang erzeugt.
"""
from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import sys
import tomllib
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "verein.toml"
TERMINE = ROOT / "data" / "termine.csv"
OUT = ROOT / "public"
PRIVATE = ROOT / "build"

STUFEN = {"oeffentlich", "trainer", "intern", "vorstand"}
WOCHENTAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
BYDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


# --------------------------------------------------------------------------
# Daten
# --------------------------------------------------------------------------
@dataclass
class Termin:
    id: str
    titel: str
    start: datetime | date
    ende: datetime | date
    ganztaegig: bool
    wiederholung: str
    ort: str
    abteilung: str
    kategorie: str
    mannschaft: str
    sichtbarkeit: str
    beschreibung: str
    absagen: dict = field(default_factory=dict)  # Datum -> Grund
    auch_feiertags: bool = False
    zielgruppe: str = ""                          # Jugend / Erwachsene / Alle
    ausnahmen: set = field(default_factory=set)   # entfallende Tage (z. B. Feiertage)


@dataclass
class Feed:
    id: str
    name: str
    beschreibung: str
    zugang: str
    sichtbarkeit: list[str]
    abteilungen: list[str] = field(default_factory=list)
    mannschaften: list[str] = field(default_factory=list)
    kategorien: list[str] = field(default_factory=list)
    inkl_hauptverein: bool = False
    externe_feeds: list[str] = field(default_factory=list)
    ohne_kategorien: list[str] = field(default_factory=list)
    gruppe: str = ""
    kompakt: bool = False
    zielgruppen: list[str] = field(default_factory=list)
    ohne_zielgruppen: list[str] = field(default_factory=list)
    jahrgang: int = 0
    inkl_abteilung: list[str] = field(default_factory=list)  # abteilungsweite Termine ohne Mannschaft

    def passt(self, t: Termin) -> bool:
        if t.sichtbarkeit not in self.sichtbarkeit:
            return False
        if t.zielgruppe and t.zielgruppe in self.ohne_zielgruppen:
            return False
        if self.inkl_hauptverein and t.abteilung == "Hauptverein" and t.kategorie != "Gremium":
            return True
        if t.abteilung in self.inkl_abteilung and not t.mannschaft and t.kategorie != "Gremium":
            return True
        if self.abteilungen and t.abteilung not in self.abteilungen:
            return False
        if t.kategorie in self.ohne_kategorien:
            return False
        # Kategorien / Mannschaften / Zielgruppen: Sind mehrere angegeben, reicht eine Übereinstimmung.
        gesetzt = [wert in liste for liste, wert in ((self.kategorien, t.kategorie),
                                                     (self.mannschaften, t.mannschaft)) if liste]
        if self.zielgruppen:
            # Termine für alle zählen zu jeder Zielgruppe – außer Gremien, die brauchen eine ausdrückliche Angabe.
            fuer_alle = t.zielgruppe in ("", "Alle") and t.kategorie != "Gremium"
            gesetzt.append(fuer_alle or t.zielgruppe in self.zielgruppen)
        return any(gesetzt) if gesetzt else True


def zielgruppe_fuer(angabe: str, mannschaft: str) -> str:
    """Für wen ein Termin ist: Jugend, Erwachsene oder Alle.

    Mit Mannschaft entscheidet die Mannschaft: Jugendmannschaften (Bambini, U..) sind Jugend,
    alle anderen Erwachsene – es sei denn, bei so einer Mannschaft ist ausdrücklich Jugend gewählt.
    Ohne Mannschaft gilt die Angabe; leer heißt Alle.
    """
    if mannschaft:
        if mannschaft == "Bambini" or re.fullmatch(r"U\d+", mannschaft):
            return "Jugend"
        return "Jugend" if angabe == "Jugend" else "Erwachsene"
    return angabe or "Alle"


def fehler(msg: str) -> None:
    print(f"FEHLER: {msg}", file=sys.stderr)
    sys.exit(1)


def warnung(msg: str) -> None:
    print(f"Warnung: {msg}", file=sys.stderr)


def lies_zeit(wert: str, ganztaegig: bool, tz: ZoneInfo, zeile: int):
    wert = wert.strip()
    try:
        if ganztaegig:
            return date.fromisoformat(wert[:10])
        return datetime.strptime(wert, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
    except ValueError:
        fehler(f"termine.csv Zeile {zeile}: Zeit '{wert}' nicht lesbar "
               f"(Format JJJJ-MM-TT HH:MM bzw. JJJJ-MM-TT bei ganztägig)")


def lade_termine(tz: ZoneInfo) -> list[Termin]:
    termine, ids = [], set()
    with TERMINE.open(encoding="utf-8-sig", newline="") as f:
        for nr, r in enumerate(csv.DictReader(f), start=2):
            if not (r.get("titel") or "").strip():
                continue
            ganz = (r.get("ganztaegig") or "").strip().lower() in {"ja", "x", "1", "true"}
            tid = (r.get("id") or "").strip() or f"zeile-{nr}"
            if tid in ids:
                fehler(f"termine.csv Zeile {nr}: id '{tid}' doppelt")
            ids.add(tid)
            sicht = (r.get("sichtbarkeit") or "oeffentlich").strip().lower()
            if sicht not in STUFEN:
                fehler(f"termine.csv Zeile {nr}: sichtbarkeit '{sicht}' unbekannt ({', '.join(sorted(STUFEN))})")
            start = lies_zeit(r["start"], ganz, tz, nr)
            ende = lies_zeit(r.get("ende") or r["start"], ganz, tz, nr)
            if ganz:
                ende = ende + timedelta(days=1)  # iCal: Ende exklusiv
            elif ende <= start:
                ende = start + timedelta(hours=1)
            termine.append(Termin(
                id=tid, titel=r["titel"].strip(), start=start, ende=ende, ganztaegig=ganz,
                wiederholung=(r.get("wiederholung") or "").strip(),
                ort=(r.get("ort") or "").strip(),
                abteilung=(r.get("abteilung") or "").strip(),
                kategorie=(r.get("kategorie") or "").strip(),
                mannschaft=(r.get("mannschaft") or "").strip(),
                sichtbarkeit=sicht,
                beschreibung=(r.get("beschreibung") or "").strip(),
                zielgruppe=zielgruppe_fuer((r.get("zielgruppe") or "").strip(), (r.get("mannschaft") or "").strip()),
                # notiz_intern wird bewusst nie gelesen -> landet nie in einem Kalender
            ))
    return termine


# --------------------------------------------------------------------------
# Airtable als Quelle (wenn AIRTABLE_TOKEN und AIRTABLE_BASE gesetzt sind)
# --------------------------------------------------------------------------
SICHT_MAP = {"öffentlich": "oeffentlich", "trainer": "trainer", "intern": "intern", "vorstand": "vorstand"}
WIEDER_MAP = {"wöchentlich": "FREQ=WEEKLY", "alle 2 wochen": "FREQ=WEEKLY;INTERVAL=2",
              "monatlich": "FREQ=MONTHLY"}


def lade_airtable(tz: ZoneInfo, token: str, base: str, tabelle: str) -> list[Termin]:
    """Liest nur freigegebene Termine. Eine Anfrage pro 100 Termine."""
    from urllib.parse import quote, urlencode
    termine, offset, anfragen = [], None, 0
    while True:
        q = {"filterByFormula": "{Status}='Freigegeben'", "pageSize": "100"}
        if offset:
            q["offset"] = offset
        url = f"https://api.airtable.com/v0/{base}/{quote(tabelle)}?{urlencode(q)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                antwort = json.loads(r.read())
        except Exception as e:
            fehler(f"Airtable nicht erreichbar: {e}")
        anfragen += 1
        for rec in antwort.get("records", []):
            t = airtable_termin(rec, tz)
            if t:
                termine.append(t)
        offset = antwort.get("offset")
        if not offset:
            break
    print(f"airtable    {len(termine)} freigegebene Termine ({anfragen} API-Abrufe)")
    return termine


# Ausfälle, deren letzter Tag ("Bis", sonst "Datum") höchstens 200 Tage zurückliegt, und alle künftigen.
# 200 statt 60 Tage: Abgesagte Termine müssen mindestens ein ganzes Quartal rückwirkend als abgesagt im
# Kalender bleiben, sonst zählen sie bei einer Auswertung aus dem Kalender wieder als gehalten.
AUSFALL_FORMEL = "IS_AFTER(IF({Bis}, {Bis}, {Datum}), DATEADD(TODAY(), -200, 'days'))"


def airtable_abruf(token: str, base: str, tabelle: str, formel: str) -> tuple[list[dict], int]:
    """Liest alle Datensätze einer Tabelle, die zur Formel passen. Bricht ab, wenn das nicht gelingt:
    Ohne die Ausfälle stünden abgesagte Termine wieder als stattfindend im Kalender."""
    from urllib.parse import quote, urlencode
    records, offset, anfragen = [], None, 0
    while True:
        q = {"filterByFormula": formel, "pageSize": "100"}
        if offset:
            q["offset"] = offset
        url = f"https://api.airtable.com/v0/{base}/{quote(tabelle)}?{urlencode(q)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                antwort = json.loads(r.read())
        except Exception as e:
            fehler(f"Airtable-Tabelle '{tabelle}' nicht lesbar: {e}")
        anfragen += 1
        records += antwort.get("records", [])
        offset = antwort.get("offset")
        if not offset:
            return records, anfragen


def ostersonntag(jahr: int) -> date:
    a, b, c = jahr % 19, jahr // 100, jahr % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    monat = (h + l - 7 * m + 114) // 31
    tag = (h + l - 7 * m + 114) % 31 + 1
    return date(jahr, monat, tag)


def feiertage(jahr: int, cfg: dict) -> dict:
    """Gesetzliche Feiertage (Bayern) plus in der Konfiguration ergänzte freie Tage."""
    o = ostersonntag(jahr)
    tage = {
        date(jahr, 1, 1): "Neujahr", date(jahr, 1, 6): "Heilige Drei Könige",
        o - timedelta(days=2): "Karfreitag", o + timedelta(days=1): "Ostermontag",
        date(jahr, 5, 1): "Tag der Arbeit", o + timedelta(days=39): "Christi Himmelfahrt",
        o + timedelta(days=50): "Pfingstmontag", o + timedelta(days=60): "Fronleichnam",
        date(jahr, 8, 15): "Mariä Himmelfahrt", date(jahr, 10, 3): "Tag der Deutschen Einheit",
        date(jahr, 11, 1): "Allerheiligen", date(jahr, 12, 25): "1. Weihnachtstag",
        date(jahr, 12, 26): "2. Weihnachtstag",
    }
    for eintrag in cfg.get("feiertage", {}).get("zusaetzlich", []):
        mm, tt = eintrag["datum"].split("-")
        tage[date(jahr, int(mm), int(tt))] = eintrag.get("name", "frei")
    return tage


def wende_feiertage_an(termine: list[Termin], cfg: dict, heute: date | None = None) -> int:
    """Regelmäßige Trainings werden an Feiertagen als abgesagt markiert.

    Berücksichtigt alles vom Beginn der Serie bis 800 Tage nach heute, damit auch Serien,
    die schon lange laufen, künftige Feiertage bekommen.
    """
    kategorien = set(cfg.get("feiertage", {}).get("kategorien", ["Training"]))
    heute = heute or datetime.now(ZoneInfo(cfg["verein"]["zeitzone"])).date()
    n = 0
    for t in termine:
        if not t.wiederholung or t.auch_feiertags or t.kategorie not in kategorien:
            continue
        erster = t.start.date() if isinstance(t.start, datetime) else t.start
        bis = max(erster, heute) + timedelta(days=800)
        alle = {}
        for j in range(erster.year, bis.year + 1):
            alle.update(feiertage(j, cfg))
        for s_ in vorkommen(t, erster, bis):
            tag_ = s_.date() if isinstance(s_, datetime) else s_
            if tag_ in alle:
                t.absagen.setdefault(tag_, f"Feiertag ({alle[tag_]})")
                n += 1
    return n


def wende_ausfaelle_an(termine: list[Termin], ausfaelle: list[dict], cfg: dict) -> int:
    """Markiert Termine an den Ausfall-Tagen als abgesagt. Gibt die Zahl der Treffer zurück.

    Ein verknüpfter Termin wird immer getroffen. Ein Ausfall je Mannschaft trifft nur die
    Kategorien der Feiertagsregel (Training), keine BFV-Spiele und – wenn im Ausfall eine
    Abteilung steht – nur diese Abteilung.
    """
    kategorien = set(cfg.get("feiertage", {}).get("kategorien", ["Training"]))
    treffer = 0
    for a in ausfaelle:
        f = a.get("fields", {})
        if not f.get("Datum"):
            continue
        von = date.fromisoformat(f["Datum"][:10])
        bis = date.fromisoformat(f["Bis"][:10]) if f.get("Bis") else von
        verknuepft = set(f.get("Termin") or [])
        mannschaft = (f.get("Mannschaft") or "").strip()
        abteilung = (f.get("Abteilung") or "").strip()
        grund = (f.get("Grund") or "").strip()
        abteilungen = set()   # Abteilungen, deren Mannschaft getroffen wurde
        for t in termine:
            ueber_mannschaft = (mannschaft and t.mannschaft == mannschaft and t.kategorie in kategorien
                                and not t.id.startswith("bfv-") and (not abteilung or t.abteilung == abteilung))
            if t.id not in verknuepft and not ueber_mannschaft:
                continue
            for s_ in vorkommen(t, von, bis):
                t.absagen[s_.date() if isinstance(s_, datetime) else s_] = grund
                treffer += 1
                if t.id not in verknuepft:
                    abteilungen.add(t.abteilung)
        if len(abteilungen) > 1:
            warnung(f"Ausfall {a.get('id', '?')} für '{mannschaft}' am {von:%d.%m.%Y} trifft mehrere Abteilungen "
                    f"({', '.join(sorted(abteilungen))}) – im Ausfall die Abteilung angeben")
    return treffer


def airtable_termin(rec: dict, tz: ZoneInfo) -> Termin | None:
    f = rec.get("fields", {})
    titel = (f.get("Titel") or "").strip()
    if not titel or not f.get("Beginn"):
        warnung(f"Airtable-Termin {rec['id']} ohne Titel oder Beginn – übersprungen")
        return None
    ganz = bool(f.get("Ganztägig"))
    beginn = datetime.fromisoformat(f["Beginn"].replace("Z", "+00:00")).astimezone(tz)
    ende = (datetime.fromisoformat(f["Ende"].replace("Z", "+00:00")).astimezone(tz)
            if f.get("Ende") else None)
    if ganz:
        start = beginn.date()
        ende_w = (ende.date() if ende else start) + timedelta(days=1)
    else:
        start = beginn
        ende_w = ende if ende and ende > beginn else beginn + timedelta(hours=1, minutes=30)
    regel = WIEDER_MAP.get((f.get("Wiederholung") or "").strip().lower(), "")
    if regel and f.get("Wiederholen bis"):
        bis = datetime.combine(date.fromisoformat(f["Wiederholen bis"][:10]),
                               datetime.max.time(), tz).astimezone(timezone.utc)
        regel += f";UNTIL={bis:%Y%m%dT%H%M%SZ}"
    # Im Zweifel nicht veröffentlichen: fehlende oder unbekannte Sichtbarkeit wird nie zu "öffentlich".
    # Die Warnung nennt bewusst nur die ID, nicht den Titel (das Build-Log ist öffentlich).
    sicht_roh = (f.get("Sichtbarkeit") or "").strip().lower()
    sicht = next((v for k, v in SICHT_MAP.items() if sicht_roh.startswith(k)), None)
    if not sicht:
        warnung(f"Airtable-Termin {rec['id']}: Sichtbarkeit "
                + (f"'{f['Sichtbarkeit']}' unbekannt" if sicht_roh else "fehlt") + " – übersprungen")
        return None
    return Termin(
        id=rec["id"], titel=titel, start=start, ende=ende_w, ganztaegig=ganz,
        wiederholung=regel,
        ort=", ".join(x for x in ((f.get("Ort") or "").strip(), (f.get("Adresse") or "").strip()) if x),
        abteilung=(f.get("Abteilung") or "").strip(),
        kategorie=(f.get("Kategorie") or "").strip(),
        mannschaft=(f.get("Mannschaft") or "").strip(),
        sichtbarkeit=sicht, beschreibung=(f.get("Beschreibung") or "").strip(),
        auch_feiertags=bool(f.get("Auch an Feiertagen")),
        zielgruppe=zielgruppe_fuer((f.get("Zielgruppe") or "").strip(), (f.get("Mannschaft") or "").strip()),
        # "Notiz intern" und "Eingereicht von" werden bewusst nie gelesen
    )


# --------------------------------------------------------------------------
# iCal schreiben
# --------------------------------------------------------------------------
def esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def falte(zeile: str) -> str:
    """Zeilen nach RFC 5545 auf 75 Byte falten (UTF-8-sicher)."""
    raw = zeile.encode("utf-8")
    if len(raw) <= 75:
        return zeile
    teile, aktuell, grenze = [], b"", 75
    for ch in zeile:
        b = ch.encode("utf-8")
        if len(aktuell) + len(b) > grenze:
            teile.append(aktuell.decode("utf-8"))
            aktuell, grenze = b"", 74
        aktuell += b
    teile.append(aktuell.decode("utf-8"))
    return "\r\n ".join(teile)


VTIMEZONE_BERLIN = """BEGIN:VTIMEZONE
TZID:Europe/Berlin
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def zeitfeld(name: str, wert, tzname: str) -> str:
    if isinstance(wert, datetime):
        return f"{name};TZID={tzname}:{wert.strftime('%Y%m%dT%H%M%S')}"
    return f"{name};VALUE=DATE:{wert.strftime('%Y%m%d')}"


def vevent(t: Termin, slug: str, tzname: str, stempel: str) -> list[str]:
    erster = t.start.date() if isinstance(t.start, datetime) else t.start
    einzel_abgesagt = not t.wiederholung and erster in t.absagen
    zeilen = [
        "BEGIN:VEVENT",
        f"UID:{t.id}@{slug}",
        f"DTSTAMP:{stempel}",
        zeitfeld("DTSTART", t.start, tzname),
        zeitfeld("DTEND", t.ende, tzname),
        f"SUMMARY:{esc(t.titel)}",  # Absage steckt in STATUS:CANCELLED
    ]
    if t.wiederholung:
        zeilen.append(f"RRULE:{t.wiederholung}")
        for tag_ in sorted(t.ausnahmen):
            if isinstance(t.start, datetime):
                zeilen.append(f"EXDATE;TZID={tzname}:{datetime.combine(tag_, t.start.time()).strftime('%Y%m%dT%H%M%S')}")
            else:
                zeilen.append(f"EXDATE;VALUE=DATE:{tag_.strftime('%Y%m%d')}")
    if t.ort:
        zeilen.append(f"LOCATION:{esc(t.ort)}")
    if einzel_abgesagt:
        zeilen += ["STATUS:CANCELLED", "TRANSP:TRANSPARENT"]
        zeilen.append(f"DESCRIPTION:{esc(absage_text(t.absagen[erster], t.beschreibung))}")
    elif t.beschreibung:
        zeilen.append(f"DESCRIPTION:{esc(t.beschreibung)}")
    kats = [k for k in (t.abteilung, t.kategorie, t.mannschaft) if k]
    if kats:
        zeilen.append("CATEGORIES:" + ",".join(esc(k) for k in kats))
    zeilen.append("END:VEVENT")
    # Abgesagte Einzeltermine einer Serie: Ausnahme-Eintrag (RECURRENCE-ID) mit "Abgesagt:"
    if t.wiederholung:
        for tag, grund in sorted(t.absagen.items()):
            s = datetime.combine(tag, t.start.timetz()) if isinstance(t.start, datetime) else tag
            e = s + (t.ende - t.start)
            zeilen += ["BEGIN:VEVENT", f"UID:{t.id}@{slug}", f"DTSTAMP:{stempel}",
                       zeitfeld("RECURRENCE-ID", s, tzname), zeitfeld("DTSTART", s, tzname),
                       zeitfeld("DTEND", e, tzname), f"SUMMARY:{esc(t.titel)}",
                       f"DESCRIPTION:{esc(absage_text(grund, t.beschreibung))}",
                       "STATUS:CANCELLED", "TRANSP:TRANSPARENT"]
            if t.ort:
                zeilen.append(f"LOCATION:{esc(t.ort)}")
            zeilen.append("END:VEVENT")
    return zeilen


def absage_text(grund: str, beschreibung: str) -> str:
    text = "Fällt aus" + (f": {grund}" if grund else ".")
    return text + (f"\n\n{beschreibung}" if beschreibung else "")


def entfalte(text: str) -> list[str]:
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()


def hole_extern(url: str) -> tuple[list[list[str]], list[list[str]]]:
    """Lädt einen externen iCal-Feed und gibt (Zeitzonen, Termine) als Zeilenblöcke zurück."""
    url = url.replace("webcal://", "https://", 1)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Vereinskalender/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode("utf-8", errors="replace")
    except Exception as e:  # Netzwerkfehler sollen den Build nicht stoppen
        warnung(f"externer Feed nicht erreichbar ({url}): {e}")
        return [], []
    tzs, evs, block, art = [], [], None, None
    for z in entfalte(text):
        if z in ("BEGIN:VEVENT", "BEGIN:VTIMEZONE") and block is None:
            block, art = [z], z[6:]
        elif block is not None:
            block.append(z)
            if z == f"END:{art}":
                (evs if art == "VEVENT" else tzs).append(block)
                block = None
    return tzs, evs


def ical_text(wert: str) -> str:
    return (wert.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\"))


def ical_zeit(zeile: str, tz: ZoneInfo):
    kopf, _, wert = zeile.partition(":")
    if "VALUE=DATE" in kopf and "T" not in wert:
        return date(int(wert[:4]), int(wert[4:6]), int(wert[6:8]))
    dt = datetime.strptime(wert[:15], "%Y%m%dT%H%M%S")
    if wert.endswith("Z"):
        return dt.replace(tzinfo=timezone.utc).astimezone(tz)
    m = re.search(r"TZID=([^;:]+)", kopf)
    try:
        return dt.replace(tzinfo=ZoneInfo(m.group(1))).astimezone(tz) if m else dt.replace(tzinfo=tz)
    except Exception:
        return dt.replace(tzinfo=tz)


def externe_termine(feeds: list, tz: ZoneInfo) -> list[Termin]:
    """Holt externe Feeds (z. B. BFV) und macht daraus normale öffentliche Termine der Mannschaft."""
    termine, gesehen = [], set()
    for feed in feeds:
        mannschaft = feed.mannschaften[0] if len(feed.mannschaften) == 1 else ""
        abteilung = feed.abteilungen[0] if len(feed.abteilungen) == 1 else "Fußball"
        for url in feed.externe_feeds:
            _, evs = hole_extern(url)
            for block in evs:
                felder = {}
                for z in block:
                    name = re.split(r"[;:]", z, maxsplit=1)[0]
                    felder.setdefault(name, z)
                uid = felder.get("UID", "").partition(":")[2].strip()
                if not uid or uid in gesehen or "DTSTART" not in felder:
                    continue
                gesehen.add(uid)
                start = ical_zeit(felder["DTSTART"], tz)
                # Der BFV liefert ohne anstehende Spiele einen leeren Platzhalter (ohne Titel, Datum 1969).
                if not ical_text(felder.get("SUMMARY", ":").partition(":")[2]).strip() or start.year < 2000:
                    continue
                ende = ical_zeit(felder["DTEND"], tz) if "DTEND" in felder else start + timedelta(hours=2)
                teile = [x.strip() for x in ical_text(felder.get("SUMMARY", ":Spiel").partition(":")[2]).split(",")]
                titel = teile[0].replace("-", " – ", 1) if teile[0].count("-") == 1 else teile[0]
                termine.append(Termin(
                    id=f"bfv-{uid}", titel=titel, start=start, ende=ende,
                    ganztaegig=isinstance(start, date) and not isinstance(start, datetime),
                    wiederholung="", ort=ical_text(felder.get("LOCATION", ":").partition(":")[2]).strip(),
                    abteilung=abteilung, kategorie="Spiel", mannschaft=mannschaft, sichtbarkeit="oeffentlich",
                    zielgruppe=zielgruppe_fuer("", mannschaft),
                    beschreibung=", ".join(teile[1:] + ["Quelle: BFV"])))
    if termine:
        print(f"extern      {len(termine)} Spiele aus BFV-Feeds")
    return termine


class KombiFeed:
    """Mehrere Kalender in einem: ein Termin ist drin, wenn er in mindestens einem steht – aber nur einmal."""
    def __init__(self, feeds: list):
        self.feeds = feeds
        self.id = "_".join(f.id for f in feeds)
        praefix = feeds[0].name.split(" – ")[0]
        self.name = praefix + " – " + " + ".join(f.name.split(" – ")[-1] for f in feeds)
        self.beschreibung = "Kombi-Kalender: " + ", ".join(f.name.split(" – ")[-1] for f in feeds)

    def passt(self, t) -> bool:
        return any(f.passt(t) for f in self.feeds)


def schreibe_ics(pfad: Path, feed: Feed, termine: list[Termin], cfg: dict, stempel: str) -> int:
    v = cfg["verein"]
    tzname = v["zeitzone"]
    zeilen = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        f"PRODID:-//{v['slug']}//Vereinskalender//DE",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(feed.name)}",
        f"X-WR-CALDESC:{esc(feed.beschreibung)}",
        f"X-WR-TIMEZONE:{tzname}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    tz_ids = set()
    if tzname == "Europe/Berlin":
        zeilen += VTIMEZONE_BERLIN.splitlines()
        tz_ids.add("Europe/Berlin")
    anzahl = 0
    for t in termine:
        if feed.passt(t):
            zeilen += vevent(t, v["slug"], tzname, stempel)
            anzahl += 1
    zeilen.append("END:VCALENDAR")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(("\r\n".join(falte(z) for z in zeilen) + "\r\n").encode("utf-8"))
    return anzahl


# --------------------------------------------------------------------------
# Prüfungen
# --------------------------------------------------------------------------
def pruefe_feeds(feeds: list[Feed]) -> list[str]:
    """Mannschaftskalender brauchen eine Abteilung, sonst landet z. B. eine U9 einer anderen Abteilung darin."""
    return [f"Kalender '{f.id}' nennt Mannschaften, aber keine Abteilung (abteilungen = [...] in verein.toml ergänzen)"
            for f in feeds if f.mannschaften and not f.abteilungen]


def pruefe_belegung(termine: list[Termin]) -> list[str]:
    """Einfache Doppelbelegungsprüfung je Ort (nur Einzeltermine mit Uhrzeit)."""
    hinweise = []
    einzel = [t for t in termine if not t.wiederholung and not t.ganztaegig and t.ort
              and t.ort.lower() not in {"auswärts", "online"}]
    einzel.sort(key=lambda t: (t.ort, t.start))
    for a, b in zip(einzel, einzel[1:]):
        if a.ort == b.ort and b.start < a.ende:
            hinweise.append(f"{a.ort}: '{a.titel}' und '{b.titel}' überschneiden sich am "
                            f"{a.start:%d.%m.%Y}")
    return hinweise


# --------------------------------------------------------------------------
# Website
# --------------------------------------------------------------------------
def termin_json(t: Termin) -> dict:
    d = {
        "titel": t.titel, "ort": t.ort, "abteilung": t.abteilung,
        "mannschaft": t.mannschaft, "ganztaegig": t.ganztaegig,
        "start": t.start.isoformat(), "beschreibung": t.beschreibung,
    }
    if t.wiederholung:
        d["regel"] = beschreibe_regel(t)
    elif (t.start.date() if isinstance(t.start, datetime) else t.start) in t.absagen:
        d["abgesagt"] = t.absagen[t.start.date() if isinstance(t.start, datetime) else t.start]
    return d


def beschreibe_regel(t: Termin) -> str:
    teile = dict(p.split("=", 1) for p in t.wiederholung.split(";") if "=" in p)
    if teile.get("FREQ") == "WEEKLY":
        tage = [WOCHENTAGE[BYDAY[d]] for d in teile.get("BYDAY", "").split(",") if d in BYDAY]
        if not tage and isinstance(t.start, (date, datetime)):
            tage = [WOCHENTAGE[t.start.weekday()]]
        uhr = f", {t.start:%H:%M} Uhr" if isinstance(t.start, datetime) else ""
        return "jeden " + " und ".join(tage) + uhr
    return "regelmäßig"


def vorkommen(t: Termin, von: date, bis: date) -> list:
    alle = _vorkommen(t, von, bis)
    if not t.ausnahmen:
        return alle
    return [s_ for s_ in alle if (s_.date() if isinstance(s_, datetime) else s_) not in t.ausnahmen]


def _vorkommen(t: Termin, von: date, bis: date) -> list:
    """Einzelne Vorkommen eines (ggf. wiederkehrenden) Termins im Zeitraum – für die Monatsansicht."""
    erster = t.start.date() if isinstance(t.start, datetime) else t.start
    dauer = t.ende - t.start
    if not t.wiederholung:
        return [t.start] if von <= erster <= bis else []
    teile = dict(p.split("=", 1) for p in t.wiederholung.split(";") if "=" in p)
    schritt = int(teile.get("INTERVAL", 1))
    ende = bis
    if "UNTIL" in teile:
        ende = min(ende, datetime.strptime(teile["UNTIL"][:8], "%Y%m%d").date())
    ergebnis = []
    if teile.get("FREQ") == "WEEKLY":
        tage = [BYDAY[d] for d in teile.get("BYDAY", "").split(",") if d in BYDAY] or [erster.weekday()]
        woche = erster - timedelta(days=erster.weekday())
        while woche <= ende:
            for wd in sorted(tage):
                d = woche + timedelta(days=wd)
                if erster <= d <= ende and d >= von:
                    ergebnis.append(datetime.combine(d, t.start.timetz()) if isinstance(t.start, datetime) else d)
            woche += timedelta(weeks=schritt)
    elif teile.get("FREQ") == "MONTHLY":
        j, m = erster.year, erster.month
        while date(j, m, 1) <= ende:
            try:
                d = date(j, m, erster.day)
                if erster <= d <= ende and d >= von:
                    ergebnis.append(datetime.combine(d, t.start.timetz()) if isinstance(t.start, datetime) else d)
            except ValueError:
                pass
            m += schritt
            j, m = j + (m - 1) // 12, (m - 1) % 12 + 1
    else:
        ergebnis = [t.start] if von <= erster <= bis else []
    return ergebnis


def schreibe_website(cfg: dict, feeds: list[Feed], termine: list[Termin], basis: str) -> None:
    v, w = cfg["verein"], cfg["website"]
    heute = datetime.now(ZoneInfo(v["zeitzone"])).date()
    grenze = heute + timedelta(days=int(w.get("vorschau_tage", 60)))

    def tag(t):
        return t.start.date() if isinstance(t.start, datetime) else t.start

    oeff = [t for t in termine if t.sichtbarkeit == "oeffentlich"]
    einzel = sorted((t for t in oeff if not t.wiederholung and heute <= tag(t) <= grenze), key=tag)
    regel = sorted((t for t in oeff if t.wiederholung), key=lambda t: (t.abteilung, t.mannschaft))
    abteilungen = sorted({t.abteilung for t in oeff if t.abteilung})

    feed_daten = [{"id": f.id, "name": f.name, "beschreibung": f.beschreibung,
                   "pfad": f"{f.id}.ics", "gruppe": f.gruppe or "Weitere Kalender",
                   "kompakt": f.kompakt, "jahrgang": f.jahrgang,
                   "art": ("mannschaft" if f.kompakt else "abteilung" if len(f.abteilungen) == 1
                           and f.abteilungen[0] != "Hauptverein" and not f.zielgruppen and not f.mannschaften
                           else "verein" if f.abteilungen == ["Hauptverein"] else "")}
                  for f in feeds if f.zugang == "oeffentlich"]
    daten = {
        "basis": basis, "feeds": feed_daten, "abteilungen": abteilungen,
        "kombi": {"max": int(cfg.get("kombi", {}).get("max", 3)),
                  "ohne": cfg.get("kombi", {}).get("ohne", ["alle"])},
        "termine": [termin_json(t) for t in einzel],
        "regelmaessig": [termin_json(t) for t in regel],
        "vorkommen": sorted(
            ({**termin_json(t), "start": s.isoformat(),
              "ende": (s + (t.ende - t.start)).isoformat() if isinstance(s, datetime) else None,
              **({"abgesagt": t.absagen[sd]} if (sd := s.date() if isinstance(s, datetime) else s) in t.absagen else {})}
             for t in oeff for s in vorkommen(t, heute - timedelta(days=62), heute + timedelta(days=400))),
            key=lambda d: d["start"]),
    }
    daten["farben"] = cfg.get("abteilungsfarben", {})
    logo_datei = Path(__file__).parent / "logo.svg"
    logo_svg = logo_datei.read_text(encoding="utf-8") if logo_datei.exists() else ""
    if logo_svg:  # Favicon in Vereinsfarbe
        (OUT / "logo.svg").write_text(logo_svg.replace("currentColor", v.get("farbe", "#26684C"))
                                      .replace("<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
                                      if 'xmlns="http' not in logo_svg[:300] else
                                      logo_svg.replace("currentColor", v.get("farbe", "#26684C")),
                                      encoding="utf-8")
    vorlage = (Path(__file__).parent / "website.html").read_text(encoding="utf-8")
    seite = (vorlage
             .replace("{{TITEL}}", html.escape(f"{w['titel']} · {v['kurzname']}"))
             .replace("{{KOPF}}", html.escape(w["titel"]))
             .replace("{{VEREIN}}", html.escape(v["name"]))
             .replace("{{UNTERTITEL}}", html.escape(w["untertitel"]))
             .replace("{{FARBE}}", v.get("farbe", "#26684C"))
             .replace("{{LOGO}}", logo_svg)
             .replace("{{DATEN}}", json.dumps(daten, ensure_ascii=False).replace("</", "<\\/")))
    (OUT / "index.html").write_text(seite, encoding="utf-8")
    # QR-Code-Bibliothek (qrcode-generator, MIT-Lizenz) lokal mitliefern
    (OUT / "qrcode.js").write_bytes((Path(__file__).parent / "qrcode.js").read_bytes())


# --------------------------------------------------------------------------
# Hauptprogramm
# --------------------------------------------------------------------------
def main() -> None:
    cfg = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg["verein"]["zeitzone"])
    basis = (os.environ.get("VK_BASIS_URL") or cfg["verein"].get("basis_url") or "").rstrip("/")
    feeds = [Feed(**{k: f[k] for k in f}) for f in cfg["feed"]]
    for f in feeds:
        unbekannt = set(f.sichtbarkeit) - STUFEN
        if unbekannt:
            fehler(f"Feed '{f.id}': unbekannte Sichtbarkeit {unbekannt}")
    at_token, at_base = os.environ.get("AIRTABLE_TOKEN"), os.environ.get("AIRTABLE_BASE")
    if at_token and at_base:
        termine = lade_airtable(tz, at_token, at_base, os.environ.get("AIRTABLE_TABELLE", "Termine"))
        print(f"feiertage   {wende_feiertage_an(termine, cfg)} Trainings an Feiertagen abgesagt")
        ausfaelle, n = airtable_abruf(at_token, at_base, "Ausfälle", AUSFALL_FORMEL)
        print(f"airtable    {len(ausfaelle)} Ausfälle ({n} API-Abrufe), "
              f"{wende_ausfaelle_an(termine, ausfaelle, cfg)} Termine als abgesagt markiert")
    else:
        termine = lade_termine(tz)
        print(f"feiertage   {wende_feiertage_an(termine, cfg)} Trainings an Feiertagen abgesagt")
    termine += externe_termine(feeds, tz)
    stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    OUT.mkdir(exist_ok=True)
    PRIVATE.mkdir(exist_ok=True)
    (OUT / ".nojekyll").write_text("")

    for f in feeds:
        if f.zugang == "oeffentlich":
            n = schreibe_ics(OUT / f"{f.id}.ics", f, termine, cfg, stempel)
            print(f"öffentlich  {f.id:<16} {n:>3} Termine")

    # Kombi-Kalender: alle Zweier-/Dreier-Kombinationen vorab erzeugen (kein Server nötig)
    from itertools import combinations
    k_cfg = cfg.get("kombi", {})
    kombinierbar = sorted((f for f in feeds if f.zugang == "oeffentlich"
                           and f.id not in k_cfg.get("ohne", ["alle"])), key=lambda f: f.id)
    n_kombi = 0
    for groesse in range(2, int(k_cfg.get("max", 3)) + 1):
        for gruppe in combinations(kombinierbar, groesse):
            kf = KombiFeed(list(gruppe))
            schreibe_ics(OUT / "kombi" / f"{kf.id}.ics", kf, termine, cfg, stempel)
            n_kombi += 1
    print(f"kombi       {n_kombi} Kombi-Kalender")

    # Interne Zugänge: pro Person ein geheimer Ordner
    roh = os.environ.get("VK_INTERN_TOKENS")
    if roh:
        zugaenge = json.loads(roh)
    else:
        demo = hashlib.sha256(b"demo-" + cfg["verein"]["slug"].encode()).hexdigest()[:24]
        zugaenge = {"Demo-Zugang": {"token": demo, "feeds": ["vorstand", "hauptverein"]}}
        warnung("VK_INTERN_TOKENS nicht gesetzt – es wird ein Demo-Zugang erzeugt")
    nach_id = {f.id: f for f in feeds}
    nach_name = {f.name.split(" – ")[-1].lower(): f for f in feeds}
    links = []
    for person, z in zugaenge.items():
        tok = z["token"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", tok):
            fehler(f"Token von '{person}' zu kurz oder ungültig (mind. 16 Zeichen, A-Z a-z 0-9 _ -)")
        teile = []
        for fid in z.get("feeds", ["intern"]):
            # Kennung (z. B. "2018-1") oder aktueller Kurzname (z. B. "u9")
            f_ = nach_id.get(fid) or nach_name.get(fid.lower())
            if not f_:
                warnung(f"Zugang '{person}': Kalender '{fid}' existiert nicht – übersprungen")
                continue
            teile.append(f_)
        if not teile:
            continue
        # Ein persönlicher Kalender pro Person: alles Gewählte in einem, jeder Termin nur einmal
        kf = KombiFeed(teile)
        n = schreibe_ics(OUT / "i" / tok / "kalender.ics", kf, termine, cfg, stempel)
        links.append(f"{person:<20} {'+'.join(f.id for f in teile):<24} {basis or '.'}/i/{tok}/kalender.ics   ({n} Termine)")
    (PRIVATE / "intern-links.txt").write_text(
        "Interne Kalender-Links – NICHT veröffentlichen\n\n" + "\n".join(links) + "\n", encoding="utf-8")
    print(f"intern      {len(links)} persönliche Links -> build/intern-links.txt")

    schreibe_website(cfg, feeds, termine, basis)
    print("website     public/index.html")

    for h in pruefe_feeds(feeds):
        warnung(h)
    for h in pruefe_belegung(termine):
        warnung("Doppelbelegung – " + h)


if __name__ == "__main__":
    main()

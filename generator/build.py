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
z. B. {"Max Muster": {"token": "k3f9...", "feeds": ["intern"]}}.
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

STUFEN = {"oeffentlich", "intern", "vorstand"}
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

    def passt(self, t: Termin) -> bool:
        if t.sichtbarkeit not in self.sichtbarkeit:
            return False
        if self.inkl_hauptverein and t.abteilung == "Hauptverein" and t.kategorie != "Gremium":
            return True
        if self.abteilungen and t.abteilung not in self.abteilungen:
            return False
        if self.kategorien and t.kategorie not in self.kategorien:
            return False
        if self.mannschaften and t.mannschaft not in self.mannschaften:
            return False
        return True


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
                # notiz_intern wird bewusst nie gelesen -> landet nie in einem Kalender
            ))
    return termine


# --------------------------------------------------------------------------
# Airtable als Quelle (wenn AIRTABLE_TOKEN und AIRTABLE_BASE gesetzt sind)
# --------------------------------------------------------------------------
SICHT_MAP = {"öffentlich": "oeffentlich", "intern": "intern", "vorstand": "vorstand"}
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
    sicht_roh = (f.get("Sichtbarkeit") or "Öffentlich").lower()
    sicht = next((v for k, v in SICHT_MAP.items() if sicht_roh.startswith(k)), "oeffentlich")
    return Termin(
        id=rec["id"], titel=titel, start=start, ende=ende_w, ganztaegig=ganz,
        wiederholung=regel, ort=(f.get("Ort") or "").strip(),
        abteilung=(f.get("Abteilung") or "").strip(),
        kategorie=(f.get("Kategorie") or "").strip(),
        mannschaft=(f.get("Mannschaft") or "").strip(),
        sichtbarkeit=sicht, beschreibung=(f.get("Beschreibung") or "").strip(),
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
    zeilen = [
        "BEGIN:VEVENT",
        f"UID:{t.id}@{slug}",
        f"DTSTAMP:{stempel}",
        zeitfeld("DTSTART", t.start, tzname),
        zeitfeld("DTEND", t.ende, tzname),
        f"SUMMARY:{esc(t.titel)}",
    ]
    if t.wiederholung:
        zeilen.append(f"RRULE:{t.wiederholung}")
    if t.ort:
        zeilen.append(f"LOCATION:{esc(t.ort)}")
    if t.beschreibung:
        zeilen.append(f"DESCRIPTION:{esc(t.beschreibung)}")
    kats = [k for k in (t.abteilung, t.kategorie, t.mannschaft) if k]
    if kats:
        zeilen.append("CATEGORIES:" + ",".join(esc(k) for k in kats))
    zeilen.append("END:VEVENT")
    return zeilen


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
    for url in feed.externe_feeds:
        tzs, evs = hole_extern(url)
        for block in tzs:
            tid = next((z[5:] for z in block if z.startswith("TZID:")), None)
            if tid and tid not in tz_ids:
                zeilen += block
                tz_ids.add(tid)
        for block in evs:
            zeilen += block
            anzahl += 1
    zeilen.append("END:VCALENDAR")
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(("\r\n".join(falte(z) for z in zeilen) + "\r\n").encode("utf-8"))
    return anzahl


# --------------------------------------------------------------------------
# Prüfungen
# --------------------------------------------------------------------------
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
                   "pfad": f"{f.id}.ics"} for f in feeds if f.zugang == "oeffentlich"]
    daten = {
        "basis": basis, "feeds": feed_daten, "abteilungen": abteilungen,
        "termine": [termin_json(t) for t in einzel],
        "regelmaessig": [termin_json(t) for t in regel],
    }
    vorlage = (Path(__file__).parent / "website.html").read_text(encoding="utf-8")
    seite = (vorlage
             .replace("{{TITEL}}", html.escape(f"{w['titel']} · {v['kurzname']}"))
             .replace("{{KOPF}}", html.escape(w["titel"]))
             .replace("{{VEREIN}}", html.escape(v["name"]))
             .replace("{{UNTERTITEL}}", html.escape(w["untertitel"]))
             .replace("{{FARBE}}", v.get("farbe", "#1d4f91"))
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
    else:
        termine = lade_termine(tz)
    stempel = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    OUT.mkdir(exist_ok=True)
    PRIVATE.mkdir(exist_ok=True)
    (OUT / ".nojekyll").write_text("")

    for f in feeds:
        if f.zugang == "oeffentlich":
            n = schreibe_ics(OUT / f"{f.id}.ics", f, termine, cfg, stempel)
            print(f"öffentlich  {f.id:<16} {n:>3} Termine")

    # Interne Zugänge: pro Person ein geheimer Ordner
    roh = os.environ.get("VK_INTERN_TOKENS")
    if roh:
        zugaenge = json.loads(roh)
    else:
        demo = hashlib.sha256(b"demo-" + cfg["verein"]["slug"].encode()).hexdigest()[:24]
        zugaenge = {"Demo-Zugang": {"token": demo, "feeds": ["intern", "vorstand"]}}
        warnung("VK_INTERN_TOKENS nicht gesetzt – es wird ein Demo-Zugang erzeugt")
    intern = {f.id: f for f in feeds if f.zugang == "intern"}
    links = []
    for person, z in zugaenge.items():
        tok = z["token"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,}", tok):
            fehler(f"Token von '{person}' zu kurz oder ungültig (mind. 16 Zeichen, A-Z a-z 0-9 _ -)")
        for fid in z.get("feeds", list(intern)):
            if fid not in intern:
                fehler(f"Zugang '{person}': interner Feed '{fid}' existiert nicht")
            n = schreibe_ics(OUT / "i" / tok / f"{fid}.ics", intern[fid], termine, cfg, stempel)
            links.append(f"{person:<20} {fid:<10} {basis or '.'}/i/{tok}/{fid}.ics   ({n} Termine)")
    (PRIVATE / "intern-links.txt").write_text(
        "Interne Kalender-Links – NICHT veröffentlichen\n\n" + "\n".join(links) + "\n", encoding="utf-8")
    print(f"intern      {len(links)} persönliche Links -> build/intern-links.txt")

    schreibe_website(cfg, feeds, termine, basis)
    print("website     public/index.html")

    for h in pruefe_belegung(termine):
        warnung("Doppelbelegung – " + h)


if __name__ == "__main__":
    main()

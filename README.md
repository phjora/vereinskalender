# Vereinskalender

Ein zentraler, abonnierbarer Vereinskalender (iCal). Termine werden an einer Stelle gepflegt,
ein Skript erzeugt daraus automatisch alle Kalender – öffentliche für die Website und
persönliche, sperrbare Links für interne Kalender.

Erster Einsatz: TSV München-Großhadern. Alles Vereinsspezifische steht in `config/verein.toml`,
damit das System auch für andere Vereine genutzt werden kann.

## Aufbau

| Pfad | Inhalt |
| --- | --- |
| `config/verein.toml` | Verein, Farben, Kalender (Feeds) mit Sichtbarkeit und Filtern |
| `data/termine.csv` | Termine – eine Zeile pro Termin |
| `generator/build.py` | erzeugt `public/*.ics`, interne Kalender und die Website |
| `generator/website.html` | Vorlage der Website |
| `generator/neuer_zugang.py` | erzeugt einen persönlichen Zugang für interne Kalender |
| `.github/workflows/kalender.yml` | baut und veröffentlicht bei jeder Änderung und stündlich |

Nur Python-Standardbibliothek (ab 3.11), keine Installation nötig.

## Termine pflegen mit Airtable (empfohlen)

Base „Vereinskalender TSV Großhadern“, Tabelle „Termine“. Eingabe über das Formular
„Termin eintragen“ oder direkt in der Tabelle; Freigabe über die Interface-Seite „Zur Freigabe“.
Nur Termine mit Status **Freigegeben** landen im Kalender. „Notiz intern“ und „Eingereicht von“
werden nie veröffentlicht.

GitHub-Secrets: `AIRTABLE_TOKEN` (Personal Access Token, nur Lesezugriff `data.records:read`
auf diese eine Base) und `AIRTABLE_BASE` (`appWarqQIpadIrt7W`). Sind sie gesetzt, liest der
Generator aus Airtable statt aus der CSV. Abruf alle 3 Stunden (Gratis-Limit 1.000 Abrufe/Monat).

## Termine pflegen ohne Airtable (`data/termine.csv`)

| Spalte | Beispiel | Hinweis |
| --- | --- | --- |
| `id` | `u17-elternabend` | eindeutig und **nie ändern** – sonst entsteht beim Abonnenten ein doppelter Termin |
| `titel` | Elternabend U17 | |
| `start`, `ende` | 2026-11-19 19:00 | bei ganztägig nur das Datum |
| `ganztaegig` | ja / nein | |
| `wiederholung` | `FREQ=WEEKLY;BYDAY=WE;UNTIL=20261216T230000Z` | optional, iCal-Regel, in Anführungszeichen wenn Kommas vorkommen |
| `ort` | Vereinsheim | wird auch für die Doppelbelegungsprüfung genutzt |
| `abteilung` | Fußball, Judo, Hauptverein | `Hauptverein` = vereinsweit |
| `kategorie` | Jugend, Training, Spiel, Gremium, Veranstaltung | |
| `mannschaft` | U9, U17 | optional |
| `sichtbarkeit` | oeffentlich / intern / vorstand | entscheidet, in welchen Kalendern der Termin landet |
| `beschreibung` | kurzer Text | landet im Kalender – keine personenbezogenen Daten |
| `notiz_intern` | | wird **nie** in einen Kalender übernommen |

## Lokal testen

```bash
python generator/build.py
cd public && python -m http.server 8000   # dann http://localhost:8000 öffnen
```

Die internen Links stehen danach in `build/intern-links.txt` (wird nicht veröffentlicht).

## Interne Zugänge

```bash
python generator/neuer_zugang.py "Max Muster" intern
```

Die Ausgabe in das GitHub-Secret `VK_INTERN_TOKENS` übernehmen (alle Personen in einem JSON-Objekt).
Zugang sperren = Eintrag aus dem Secret löschen; beim nächsten Lauf ist der Link ungültig.

## Veröffentlichen mit GitHub Pages (Prototyp)

1. Repository anlegen und diesen Ordner hochladen.
2. Settings → Pages → Source: **GitHub Actions**.
3. Optional: Settings → Secrets and variables → Actions → `VK_INTERN_TOKENS` anlegen.
4. Actions → „Kalender bauen und veröffentlichen“ → Run workflow.

Die Kalender liegen danach unter `https://<konto>.github.io/<repo>/alle.ics` usw.

**Wichtig:** Ein öffentliches Repository zeigt auch `data/termine.csv` mit allen internen Terminen.
Für den Prototyp mit Beispieldaten ist das in Ordnung. Für den echten Betrieb entweder ein privates
Repository mit Hosting bei Cloudflare Pages, oder die Termine aus einer geschützten Quelle
(z. B. Airtable über API-Schlüssel) laden statt aus der CSV im Repository.

## BFV-Spiele einbinden

In der BFV-App bei der Mannschaft den „iCal Export“ öffnen, Link kopieren und in
`config/verein.toml` beim passenden Feed unter `externe_feeds` eintragen. Der Generator holt die
Spiele bei jedem Lauf neu. Ist der BFV nicht erreichbar, läuft der Build trotzdem durch.

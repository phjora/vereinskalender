# Vereinskalender

Ein zentraler, abonnierbarer Vereinskalender (iCal). Termine werden an einer Stelle gepflegt,
ein Skript erzeugt daraus alle Kalender und eine Website: öffentliche Kalender zum Abonnieren
und persönliche, sperrbare Links für interne Termine.

Erster Einsatz: TSV München-Großhadern. Alles Vereinsspezifische steht in `config/verein.toml`,
damit das System später auch für andere Vereine genutzt werden kann.

- Website: https://phjora.github.io/vereinskalender/
- Status: Prototyp. Der Vorstand hat noch nicht freigegeben, Formulare und Interface in Airtable
  sind deshalb noch nicht veröffentlicht.

## So hängt alles zusammen

```
Airtable (Termine, Ausfälle)          BFV (iCal-Export je Mannschaft)
        │  API, nur lesend                    │
        └──────────────┬──────────────────────┘
                       ▼
        generator/build.py  (GitHub Actions)
                       ▼
        public/  →  GitHub Pages
          index.html                 Website mit Kalender, Abo-Knöpfen, QR-Codes
          <feed>.ics                 öffentliche Kalender
          kombi/<id>_<id>.ics        Kombi-Kalender (mehrere in einem Abo)
          i/<token>/kalender.ics     persönliche Kalender (geheimer Link)
```

Es gibt keinen Server. Alles wird vorab als Datei erzeugt und statisch ausgeliefert.

## Aufbau des Repositorys

| Pfad | Inhalt |
| --- | --- |
| `config/verein.toml` | Verein, Farben, Feiertagsregel, Kombi-Einstellung, alle Kalender (Feeds) |
| `generator/build.py` | der Generator, nur Python-Standardbibliothek (ab 3.11, im Workflow 3.12) |
| `generator/website.html` | Vorlage der Website (HTML, CSS und JavaScript in einer Datei) |
| `generator/logo.svg` | Vereinslogo, nutzt `currentColor` |
| `generator/qrcode.js` | QR-Code-Bibliothek, lokal eingebunden (kein CDN) |
| `generator/neuer_zugang.py` | erzeugt einen Eintrag für einen persönlichen Zugang |
| `data/termine.csv` | nur Reserve und Beispieldaten, wenn kein Airtable-Zugang gesetzt ist |
| `tests/` | automatische Prüfungen für Kalenderfilter, Feiertage und Absagen |
| `.github/workflows/kalender.yml` | testet, baut und veröffentlicht |
| `.github/workflows/tests.yml` | prüft Pull Requests (Tests und Probe-Build), veröffentlicht nichts |
| `public/`, `build/` | Ausgabe, nicht im Repository (`.gitignore`) |

## Termine: Quelle Airtable

Base „Vereinskalender TSV Großhadern“ (`appWarqQIpadIrt7W`). Sind die Secrets `AIRTABLE_TOKEN`
und `AIRTABLE_BASE` gesetzt, liest der Generator aus Airtable, sonst aus der CSV.

### Tabelle „Termine“ (`tblxiEBXMwyz8Nh4H`)

Nur Datensätze mit **Status = Freigegeben** landen im Kalender.

| Feld | Bedeutung |
| --- | --- |
| Titel, Beginn, Ende, Ganztägig | Ende fehlt oder liegt vor Beginn: 90 Minuten Dauer |
| Wiederholung, Wiederholen bis | Serie; „Wiederholen bis“ gilt einschließlich dieses Tages |
| Ort, Adresse | werden im Kalender zu einem Ort zusammengeführt |
| Abteilung | `Hauptverein` = vereinsweit |
| Kategorie | Training, Spiel, Gremium, Veranstaltung … |
| Mannschaft | z. B. U9, U17; leer = abteilungsweit |
| Zielgruppe | Alle / Jugend / Erwachsene. Leer bei Mannschaften wie „U9“ oder „Bambini“ zählt als Jugend |
| Sichtbarkeit | Öffentlich / Trainer:innen / Intern / Vorstand. Fehlt der Wert oder ist er unbekannt, wird der Termin übersprungen (Warnung im Build-Log) |
| Beschreibung | landet im Kalender, keine personenbezogenen Daten |
| Auch an Feiertagen | Ausnahme von der Feiertagsregel |
| Kalender jetzt aktualisieren | Häkchen löst einen Sofort-Neubau aus |
| Notiz intern, Eingereicht von | werden **nie** gelesen oder veröffentlicht |

### Tabelle „Ausfälle“ (`tblI2kDv3CP8A8Sou`)

Felder: Was fällt aus, Datum, Bis (optional, einschließlich), Mannschaft, Termin (Verknüpfung), Grund,
Abgesagt von. Ein Ausfall trifft alle Vorkommen im Zeitraum, die entweder zum verknüpften Termin
gehören oder zur genannten Mannschaft. BFV-Spiele sind ausgenommen, die sagt der BFV selbst ab.
Gelesen werden Ausfälle der letzten 60 Tage und alle künftigen.

### Formulare, Interface, Automationen

- Formulare „Termin eintragen“ und „Termin absagen“, Interface „Kalender-Verwaltung“
  (Seiten: Zur Freigabe, Ausfälle, Kalender).
- Drei Automationen legen im Repository ein Issue „Kalender aktualisieren …“ an: bei Freigabe,
  per Häkchen, bei einer Absage. Das Issue startet den Workflow und wird danach geschlossen.

### Grenzen des kostenlosen Airtable-Tarifs

1.000 Datensätze je Base, 5 Bearbeiter, 1.000 API-Abrufe und 100 Automation-Läufe pro Monat.
Ein Build braucht 2 Abrufe (Termine, Ausfälle), solange es unter 100 Termine sind. Deshalb läuft
der geplante Abgleich nur alle 3 Stunden.

## Regeln im Generator

**Sichtbarkeit.** Vier Stufen: `oeffentlich`, `trainer`, `intern`, `vorstand`. Jeder Feed nennt,
welche Stufen er enthält. Öffentliche Feeds enthalten nur `oeffentlich`.

**Filter eines Feeds** (`Feed.passt` in `build.py`), in dieser Reihenfolge:

1. Sichtbarkeit muss passen.
2. `ohne_zielgruppen` schließt aus.
3. `inkl_hauptverein`: vereinsweite Termine kommen dazu, außer Kategorie Gremium.
4. `inkl_abteilung`: abteilungsweite Termine ohne Mannschaft kommen dazu, außer Gremium.
5. `abteilungen` grenzt ein, `ohne_kategorien` schließt aus.
6. `kategorien`, `mannschaften`, `zielgruppen`: Sind mehrere gesetzt, reicht ein Treffer.

**Feiertage.** Serien der Kategorie Training werden an gesetzlichen Feiertagen in Bayern sowie am
24.12. und 31.12. als abgesagt markiert, nicht gelöscht. Ausnahme: Häkchen „Auch an Feiertagen“.
Berücksichtigt wird alles vom Beginn der Serie bis 800 Tage in die Zukunft.
Schulferien werden bewusst nicht berücksichtigt.

**Absagen.** Abgesagte Termine bleiben im Kalender, mit `STATUS:CANCELLED` und
`TRANSP:TRANSPARENT`, bei Serien als Ausnahme mit `RECURRENCE-ID`. Der Titel bekommt kein eigenes
Präfix, weil das iPhone sonst „ABGESAGT: Abgesagt: …“ zeigt. Der Grund steht in der Beschreibung.

**BFV-Spiele.** Die iCal-Links aus der BFV-App („iCal Export“ bei der Mannschaft) stehen in
`verein.toml` unter `externe_feeds`. Der Generator wandelt sie in normale Termine um (Kategorie
Spiel, öffentlich, ID `bfv-<uid>`). Ist der BFV nicht erreichbar, läuft der Build trotzdem durch.

**Mannschaftskalender.** Die Feed-ID ist Jahrgang plus Nummer, z. B. `2018-1` (U9) und `2010-1`
(U17). Zum Saisonwechsel werden nur `name` und `mannschaften` hochgezählt, Abo-Links und QR-Codes
bleiben gültig. Eine zweite Mannschaft desselben Jahrgangs bekommt `-2`.

**Kombi-Kalender.** Für alle öffentlichen Feeds außer `alle` werden sämtliche Zweier- und
Dreier-Kombinationen erzeugt: `public/kombi/<id>_<id>.ics`, IDs alphabetisch sortiert. Jeder Termin
steht darin nur einmal. Aktuell 560 Dateien bei 15 kombinierbaren Feeds; die Zahl wächst schnell mit jedem
weiteren Feed (`[kombi] max` und `ohne` in der Konfiguration).

**Termin-IDs.** Die UID im Kalender ist die Airtable-Record-ID. Sie darf sich nie ändern, sonst
entsteht beim Abonnenten ein doppelter Termin.

**Prüfung.** Der Build warnt bei Doppelbelegung eines Orts.

## Persönliche Zugänge

Interne Termine gibt es nur über persönliche Links. Das Secret `VK_INTERN_TOKENS` ist ein
JSON-Objekt:

```json
{"Name": {"token": "mindestens-16-zeichen", "feeds": ["vorstand", "2018-1", "2010-1"]}}
```

Pro Person entsteht genau ein Kalender unter `i/<token>/kalender.ics`, der alles Gewählte enthält,
jeden Termin einmal. `feeds` nimmt Feed-IDs; die aktuellen Kurznamen (`u9`, `u17`) funktionieren als
Alias, sind aber nicht saisonfest. Unbekannte Namen geben nur eine Warnung.

```bash
python generator/neuer_zugang.py "Max Muster" intern
```

Die Ausgabe in das Secret übernehmen. Sperren = Eintrag löschen, beim nächsten Build ist der Link
tot. Die Bausteine `trainer`, `intern`, `vorstand` bauen aufeinander auf (siehe Konfiguration).

## Build und Veröffentlichung

Workflow „Kalender bauen und veröffentlichen“, ein Job `bauen`. Auslöser:

| Auslöser | Zweck |
| --- | --- |
| `push` auf `main` | Änderungen an Code oder Konfiguration |
| `schedule` (`17 */3 * * *`) | regelmäßiger Abgleich, vor allem für BFV-Verlegungen |
| `workflow_dispatch` | manuell |
| `issues: opened` | Sofort-Neubau aus Airtable; nur Issues des Repo-Besitzers mit Titel „Kalender aktualisieren…“ |

Secrets (Settings → Secrets and variables → Actions): `AIRTABLE_TOKEN` (nur `data.records:read`
auf diese eine Base), `AIRTABLE_BASE`, `VK_INTERN_TOKENS`. Die Tokens der persönlichen Links werden
in den Logs maskiert.

Bekannt:

- GitHub verzögert geplante Läufe bei kostenlosen Konten. In der Praxis läuft der Abgleich etwa
  alle 9 Stunden statt alle 3. Sofort-Neubauten sind nicht betroffen.
- Schlägt nur der Schritt `deploy-pages` fehl („No artifacts named github-pages“), ist das eine
  Störung bei GitHub. Lauf neu starten, fertig.

## Lokal bauen und testen

```bash
python -m unittest discover tests              # automatische Tests, dauert unter einer Sekunde
python generator/build.py                      # ohne Secrets: Beispieldaten aus data/termine.csv
cd public && python -m http.server 8000        # http://localhost:8000
```

Die Tests in `tests/` arbeiten nur mit erfundenen Terminen, ohne Netz und ohne Airtable. Sie prüfen
die Filterregeln einzeln, die Kalender aus `config/verein.toml` (welcher Termin landet wo),
Feiertage, Ausfälle und die iCal-Ausgabe abgesagter Termine. Sie laufen bei jedem Pull Request und
vor jeder Veröffentlichung; schlägt einer fehl, bleibt der bisherige Stand online. Wer eine Regel
oder einen Kalender bewusst ändert, passt den zugehörigen Test im selben Schritt an.

Mit echten Daten: `AIRTABLE_TOKEN` und `AIRTABLE_BASE` als Umgebungsvariablen setzen. Die
persönlichen Links stehen nach dem Build in `build/intern-links.txt` (wird nicht veröffentlicht).
Ohne `VK_INTERN_TOKENS` entsteht ein Demo-Zugang.

## Datenschutz

- Das Repository und die Seite sind öffentlich. Keine Tokens, keine echten internen Termine und
  keine personenbezogenen Daten ins Repository schreiben, auch nicht in Beispiele oder Commits.
- Bei Kindern nur Vornamen, und nur wenn es nötig ist.
- Persönliche Links sind geheim, aber nicht passwortgeschützt: Wer den Link hat, sieht den Kalender.
  Vor der Ausgabe an weitere Personen braucht es echte Zugänge (siehe offene Punkte in `CLAUDE.md`).

## Für einen anderen Verein nutzen

Neue `config/verein.toml` (Name, Slug, Farbe, Feeds), eigenes Logo, eigene Airtable-Base mit
denselben Feldnamen, Secrets setzen, Pages auf „GitHub Actions“ stellen. Der Code bleibt gleich.
Noch fest verdrahtet sind die bayerischen Feiertage, die Texte der Website und der Standard
„Fußball“ als Abteilung für externe Feeds.

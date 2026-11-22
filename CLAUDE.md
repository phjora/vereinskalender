# Hinweise für Claude Code

Aufbau, Datenmodell und Regeln stehen in der README: @README.md

Diese Datei ergänzt, wie hier gearbeitet wird und was offen ist. Das Repository ist öffentlich,
deshalb stehen hier keine Namen und keine Vereinsinterna.

## Wer und wozu

Der Betreiber ist ehrenamtlich im Vorstand des TSV München-Großhadern und Jugendtrainer (U9, U17).
Er ist kein Vollzeit-Entwickler, kann aber Code lesen. Das Projekt soll später als Vereinstool auch
anderen Vereinen dienen, also nichts TSV-Spezifisches in den Code schreiben, sondern in
`config/verein.toml`.

## Arbeitsweise

- Antworten auf Deutsch, kurz, Ergebnis zuerst. Fachbegriffe erklären oder weglassen.
- Vor größeren Umbauten kurz sagen, was sich ändert. Kleine Korrekturen direkt machen.
- Oberstes Ziel ist einfache Bedienung für Ehrenamtliche: lieber eine Regel im Generator als ein
  weiteres Feld im Formular.
- Vereinstexte (Website, Formulare, Mails): locker und natürlich, nicht werblich. „Übungsleitende“
  statt „Übungsleiter“, „Trainer:innen“.
- Proaktiv Ideen nennen, wie sich das Tool weiterentwickeln lässt.
- Nur Python-Standardbibliothek, kein Build-Schritt, keine externen Skripte oder Schriften von CDNs.

## Was du nie tust

- Secrets setzen, ändern oder ausgeben (`AIRTABLE_TOKEN`, `AIRTABLE_BASE`, `VK_INTERN_TOKENS`).
  Das macht der Betreiber selbst in den GitHub-Einstellungen. Du nennst ihm den genauen Inhalt.
- Persönliche Links oder Tokens in Antworten, Commits, Issues oder Logs schreiben.
- In Airtable etwas löschen, ohne vorher zu fragen. Formulare und Interface nicht veröffentlichen,
  das passiert erst nach Freigabe durch den Vorstand.
- Termin-IDs, Feed-IDs oder Dateinamen der Kalender ändern. Bestehende Abos würden brechen oder
  Termine doppelt zeigen. Wenn es unvermeidbar ist: vorher fragen und eine Weiterleitung einplanen.
- Echte interne Termine oder Namen in `data/termine.csv`, Tests oder Beispiele übernehmen.

## Ändern, prüfen, ausliefern

1. `git pull`, dann ändern.
2. `python -m unittest discover tests` und `python generator/build.py` lokal laufen lassen (ohne
   Secrets, mit Beispieldaten). Tests grün, Build ohne FEHLER; Warnungen lesen. Ändert sich eine
   Regel oder ein Kalender absichtlich, den Test im selben Commit anpassen.
3. Bei Änderungen an der iCal-Ausgabe eine erzeugte `.ics` ansehen: Zeilenenden CRLF, Zeilen
   gefaltet, `UID` unverändert. Bei Änderungen an der Website `public/index.html` im Browser prüfen,
   auch in schmaler Breite (die meisten kommen übers Handy).
4. Push auf `main` veröffentlicht sofort. Danach `gh run watch` oder `gh run list -L 3`.

Die Live-Daten kommen aus Airtable und sind lokal nur mit Token sichtbar. Ob echte Termine richtig
ankommen, zeigt das Build-Log (Zeilen `airtable`, `feiertage`, `extern`, `öffentlich`, `kombi`).

## Termine und Absagen auf Zuruf

Der Betreiber schreibt oft nur „Training U17 fällt heute aus“ oder „neuer Termin am …“. Mit dem
Airtable-Connector:

- Neuer Termin: Datensatz in „Termine“ anlegen. Status „Freigegeben“ nur, wenn er das so sagt;
  sonst als Vorschlag zeigen.
- Absage: Datensatz in „Ausfälle“ mit Datum, Mannschaft oder verknüpftem Termin und Grund.
- Die Automationen bauen den Kalender danach selbst neu. Ohne Connector: sagen, was er im Formular
  eintragen soll.

IDs: Base `appWarqQIpadIrt7W`, Termine `tblxiEBXMwyz8Nh4H`, Ausfälle `tblI2kDv3CP8A8Sou`.
Auswahloptionen (z. B. neue Abteilung) lassen sich über die API nicht ändern, nur per
`typecast` beim Anlegen eines Datensatzes erzeugen.

## Offene Punkte

Vor dem Start mit weiteren Personen:

- Echte persönliche Zugänge, bevor eine zweite Person interne Termine sieht. Heute liegt alles in
  einem Secret, das nur der Betreiber pflegen kann, und der Name aus dem Secret taucht bei einer
  Warnung im öffentlichen Build-Log auf.
- Im Secret die Kurznamen `u9`/`u17` durch `2018-1`/`2010-1` ersetzen (macht der Betreiber).
- Prüfen, wie Google Kalender und Outlook `STATUS:CANCELLED` ohne Titel-Präfix darstellen. Auf dem
  iPhone passt es.
- Alte Kategorie-Option „Jugend“ in Airtable entfernen (abgelöst durch das Feld Zielgruppe).

Technik:

- Zuverlässigerer Taktgeber für den regelmäßigen Abgleich (GitHub-Zeitplan läuft real nur etwa alle
  9 Stunden).
- Zahl der Kombi-Kalender begrenzen, sobald viele Mannschaften dazukommen.
- Lösung für den Saisonwechsel zum Stichtag (Namen hochzählen, BFV-IDs prüfen).
- Entscheiden, ob Spiele auch aus dem Feed `fussball-jugend` herausfallen sollen.
- Optionales Häkchen je Ausfall „aus dem Kalender entfernen“ statt als abgesagt zeigen.
- Tests decken `Feed.passt`, Feiertage und Absagen ab. Noch ohne Tests: Einlesen aus Airtable
  (`airtable_termin`), BFV-Umwandlung, persönliche Zugänge, Website.

Bekannte Abweichungen zwischen README und Code, noch nicht entschieden:

- Unbekannter Wert im Feld Sichtbarkeit wird als öffentlich behandelt statt übersprungen.
- Feiertagsregel rechnet nur 800 Tage ab Serienbeginn.
- Ausfälle, die vor mehr als 60 Tagen begannen und noch laufen, werden nicht gelesen.
- Doppelbelegung prüft nur Einzeltermine, keine Serien.
- Dauer ohne Ende: 90 Minuten bei Airtable, 60 bei der CSV.
- Zu kurzer Token oder kaputtes JSON im Secret stoppt den Build.
- Mannschaftskalender filtern nur nach Mannschaftsname, nicht nach Abteilung.
- Reste: Kopfkommentar in `build.py`, unbenutztes `ausnahmen`/`EXDATE`, Kategorie „Jugend“ in der
  Beispiel-CSV.

Größer gedacht:

- Stufe 1: Zu- und Absagen über Links im Termin, die in Airtable landen.
- Stufe 2: Plattform mit Anmeldung, in der abgesagte Termine im eigenen Kalender verschwinden oder
  markiert werden.
- Anbindung des Ergebnistrackers (auf der Website bereits als „kommt bald“ vorgemerkt).
- Für andere Vereine: Feiertage je Bundesland, Website-Texte in die Konfiguration, eigenes Hosting
  ohne öffentliches Repository.

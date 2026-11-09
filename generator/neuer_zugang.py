#!/usr/bin/env python3
"""Erzeugt einen neuen persönlichen Zugang für interne Kalender.

Aufruf:  python generator/neuer_zugang.py "Max Muster" intern
         python generator/neuer_zugang.py "Erika Beispiel" intern vorstand

Ausgabe ist ein JSON-Schnipsel für das GitHub-Secret VK_INTERN_TOKENS.
Zum Sperren eines Zugangs den Eintrag aus dem Secret löschen – beim nächsten
Lauf ist der Link tot. Zum Erneuern einfach einen neuen Token erzeugen.
"""
import json
import secrets
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)
name, feeds = sys.argv[1], sys.argv[2:] or ["intern"]
eintrag = {name: {"token": secrets.token_urlsafe(18), "feeds": feeds}}
print(json.dumps(eintrag, ensure_ascii=False, indent=2))

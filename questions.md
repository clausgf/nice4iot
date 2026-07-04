# Offene Fragen zur API-Dokumentation

Bitte die leeren Felder `[ ]` ausfüllen oder die Aussage bestätigen/korrigieren.

---

## `POST /api/telemetry/{project}/{device}/{kind}`

**1. Nicht-numerische Payload-Werte**
Was passiert mit nicht-numerischen Werten im JSON-Payload (z. B. `"status": "ok"`)?

- [ ] Werden stillschweigend ignoriert
- [ ] Werden unverändert an das Backend weitergeleitet (Backend entscheidet)
- [ ] Führen zu einem 400-Fehler

**2. Messzeitstempel**
Wird der Zeitstempel vom Server (Ankunftszeit) oder vom Gerät (im Payload) gesetzt?

- [ ] Server-seitig (Ankunftszeit)
- [ ] Gerät liefert Zeitstempel im Payload — Feldname: `___________`

**3. `kind`-Label-Konventionen**
Das arduino4iot-Framework verwendet `system` für eingebaute Metriken (Batterie, RSSI, Boot-Zähler).
Gibt es weitere reservierte oder konventionelle Werte für `kind`?

- [ ] Nein, außer `system` gibt es keine Konvention
- [ ] Ja: `___________`

---

## `POST /api/log/{project}/{device}`

**4. Maximale Body-Größe**
Der Telemetrie-Endpunkt prüft `app_config.max_upload_size`. Der Log-Endpunkt liest den Body mit `request.body()` ohne erkennbare Größenbeschränkung.

- [ ] Kein Limit gewünscht (Logs können beliebig groß sein)
- [ ] Sollte dasselbe Limit wie der Upload-Endpunkt bekommen
- [ ] Eigenes Limit: `___________` Bytes

**5. Content-Type-Validierung**
Aktuell wird kein Content-Type geprüft; der Body wird als UTF-8 dekodiert.

- [ ] Kein Content-Type erzwingen (so lassen)
- [ ] `text/plain` als Pflicht-Content-Type dokumentieren/erzwingen

---

## `HEAD / GET / PUT /api/file/{project}/{device}/{filename}`

**6. Dateinamen-Validierung**
`is_valid_filename()` wird beim Forwarding- und Telemetrie-Endpunkt geprüft, aber **nicht** beim `filename`-Parameter des File-Endpunkts.

- [ ] Validierung hinzufügen (empfohlen)
- [ ] Absichtlich nicht validiert — Begründung: `___________`

**7. Teilweiser Schreibvorgang bei 413**
Wenn beim PUT-Upload die Größenbeschränkung überschritten wird, bleibt die Datei **abgeschnitten** auf dem Datenträger zurück.

- [ ] So lassen (abgeschnittene Datei auf Disk ist akzeptabel)
- [ ] Datei bei Fehler löschen (atomarer Upload)

**8. Verzeichnis-Erstellung beim PUT**
Existiert das Geräte-Unterverzeichnis (`<projects_dir>/<project>/<device>/`) beim ersten PUT garantiert, oder kann der Upload still fehlschlagen?

- [ ] Wird automatisch angelegt (kein Problem)
- [ ] Muss noch implementiert werden

---

## `POST /api/provision`

**9. Ablaufzeitpunkt im Response**
Soll `ProvisioningResponse` den Ablaufzeitpunkt des Tokens (`expires_at`) enthalten, damit Geräte die Re-Provisionierung proaktiv planen können?

- [ ] Nein, Geräte sollen einfach bei Bedarf re-provisionieren (401 als Signal)
- [ ] Ja, `expires_at` (ISO 8601) in die Response aufnehmen

**10. Maximale Token-Anzahl pro Gerät**
Aktuell gibt es kein Limit für angesammelte Token; nur abgelaufene Token werden beim nächsten Provisionierungsaufruf bereinigt.

- [ ] Absichtlich kein Limit (so lassen)
- [ ] Maximale Anzahl aktiver Token: `___________`

---

## `app/core/project.py` — `get_project()`

**11. `check_active`-Parameter**
`get_project()` wirft bei inaktiven Projekten immer einen 403-Fehler, unabhängig vom Parameter `check_active`. Der Parameter scheint keinen Effekt zu haben.

- [ ] Bug — `check_active=False` soll inaktive Projekte durchlassen
- [ ] Absichtlich so (Parameter ist veraltet/überflüssig und kann entfernt werden)
- [ ] Anderes Verhalten gewünscht: `___________`

-- Fristen, Erinnerungen und Vorgänge (Phase 5). Tags liegen weiterhin als JSON in documents.tags.

CREATE TABLE cases (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    reference TEXT,                       -- z. B. Aktenzeichen, Vertrags- oder Versicherungsnummer
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);
CREATE INDEX cases_reference ON cases(reference) WHERE reference IS NOT NULL;

CREATE TABLE document_cases (
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'auto')),
    created_at TEXT NOT NULL,
    PRIMARY KEY (document_id, case_id)
);
CREATE INDEX document_cases_case ON document_cases(case_id);

CREATE TABLE deadlines (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    case_id INTEGER REFERENCES cases(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other'
        CHECK (kind IN ('payment', 'cancellation', 'objection', 'response', 'appointment', 'resubmission', 'other')),
    due_date TEXT NOT NULL,               -- JJJJ-MM-TT
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'dismissed')),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'document')),
    explicit INTEGER,                     -- 1 = Datum steht wörtlich im Dokument
    quote TEXT,
    remind_days INTEGER NOT NULL DEFAULT 3 CHECK (remind_days BETWEEN 0 AND 365),
    notified_stage INTEGER NOT NULL DEFAULT 0,  -- 0 = nichts, 1 = Vorab-Erinnerung, 2 = Fälligkeit
    notified_at TEXT,
    done_at TEXT,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX deadlines_open_due ON deadlines(status, due_date);
CREATE INDEX deadlines_document ON deadlines(document_id);
CREATE UNIQUE INDEX deadlines_from_document ON deadlines(document_id, kind, due_date) WHERE source = 'document';

-- Bestand: bereits analysierte Dokumente mit künftigem Fälligkeitsdatum bzw. künftigen Fristen übernehmen.
-- Vergangene Daten werden bewusst nicht übernommen (sonst erschienen alte, längst bezahlte Rechnungen als überfällig).
INSERT OR IGNORE INTO deadlines(document_id, title, kind, due_date, source, explicit, remind_days, created_at, updated_at)
SELECT d.id,
       CASE WHEN json_extract(d.metadata, '$.amount') IS NOT NULL OR lower(COALESCE(d.document_type, '')) LIKE '%rechnung%' THEN 'Zahlung' ELSE 'Frist' END
         || COALESCE(': ' || NULLIF(trim(COALESCE(d.sender, '') || CASE WHEN d.sender IS NOT NULL AND d.document_type IS NOT NULL THEN ' – ' ELSE '' END || COALESCE(d.document_type, '')), ''), ''),
       CASE WHEN json_extract(d.metadata, '$.amount') IS NOT NULL OR lower(COALESCE(d.document_type, '')) LIKE '%rechnung%' THEN 'payment' ELSE 'other' END,
       json_extract(d.metadata, '$.due_date'), 'document', 1, 3,
       strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
FROM documents d
WHERE json_valid(d.metadata)
  AND json_extract(d.metadata, '$.due_date') GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND json_extract(d.metadata, '$.due_date') >= date('now');

INSERT OR IGNORE INTO deadlines(document_id, title, kind, due_date, source, explicit, quote, remind_days, created_at, updated_at)
SELECT d.id,
       CASE json_extract(j.value, '$.kind')
         WHEN 'payment' THEN 'Zahlung' WHEN 'cancellation' THEN 'Kündigung' WHEN 'objection' THEN 'Widerspruch'
         WHEN 'response' THEN 'Antwort' WHEN 'appointment' THEN 'Termin' WHEN 'resubmission' THEN 'Wiedervorlage' ELSE 'Frist' END
         || COALESCE(': ' || NULLIF(trim(COALESCE(d.sender, '') || CASE WHEN d.sender IS NOT NULL AND d.document_type IS NOT NULL THEN ' – ' ELSE '' END || COALESCE(d.document_type, '')), ''), ''),
       CASE WHEN json_extract(j.value, '$.kind') IN ('payment', 'cancellation', 'objection', 'response', 'appointment', 'resubmission')
            THEN json_extract(j.value, '$.kind') ELSE 'other' END,
       json_extract(j.value, '$.date'), 'document',
       CASE WHEN json_extract(j.value, '$.explicit') THEN 1 ELSE 0 END,
       substr(json_extract(j.value, '$.quote'), 1, 300), 3,
       strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now'), strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')
FROM documents d, json_each(json_extract(d.metadata, '$.deadlines')) j
WHERE json_valid(d.metadata)
  AND json_type(d.metadata, '$.deadlines') = 'array'
  AND json_extract(j.value, '$.date') GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'
  AND json_extract(j.value, '$.date') >= date('now');

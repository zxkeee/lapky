ALTER TABLE shelters ADD COLUMN oblast    TEXT;
ALTER TABLE shelters ADD COLUMN status    TEXT NOT NULL DEFAULT 'published';
ALTER TABLE shelters ADD COLUMN source    TEXT NOT NULL DEFAULT 'seed';
ALTER TABLE shelters ADD COLUMN osm_id    TEXT;
ALTER TABLE shelters ADD COLUMN edited_at TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_shelters_osm           ON shelters(osm_id) WHERE osm_id IS NOT NULL;
CREATE INDEX        IF NOT EXISTS idx_shelters_status_oblast ON shelters(status, oblast);
CREATE INDEX        IF NOT EXISTS idx_shelters_geo           ON shelters(lat, lng);

UPDATE shelters SET oblast = CASE WHEN city = 'Київ' THEN 'kyiv' ELSE 'kyivska' END WHERE oblast IS NULL;

-- Масштаб на всю Україну: область, статус публікації, джерело запису, зв'язок з OSM.
ALTER TABLE shelters ADD COLUMN oblast    TEXT;
ALTER TABLE shelters ADD COLUMN status    TEXT NOT NULL DEFAULT 'published';  -- published / pending / hidden
ALTER TABLE shelters ADD COLUMN source    TEXT NOT NULL DEFAULT 'seed';       -- seed / admin / osm / application
ALTER TABLE shelters ADD COLUMN osm_id    TEXT;                               -- напр. node/123456
ALTER TABLE shelters ADD COLUMN edited_at TEXT;                               -- остання ручна правка (імпорт її не перезаписує)

CREATE UNIQUE INDEX IF NOT EXISTS idx_shelters_osm           ON shelters(osm_id) WHERE osm_id IS NOT NULL;
CREATE INDEX        IF NOT EXISTS idx_shelters_status_oblast ON shelters(status, oblast);
CREATE INDEX        IF NOT EXISTS idx_shelters_geo           ON shelters(lat, lng);

UPDATE shelters SET oblast = CASE WHEN city = 'Київ' THEN 'kyiv' ELSE 'kyivska' END WHERE oblast IS NULL;

ALTER TABLE cp_job_items
    ADD COLUMN IF NOT EXISTS content_source_json JSONB NOT NULL DEFAULT '{"mode":"original","details":{}}'::jsonb;

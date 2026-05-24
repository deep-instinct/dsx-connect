ALTER TABLE cp_job_items
    ADD COLUMN IF NOT EXISTS delivery_requirements_json JSONB NOT NULL DEFAULT '{"wait_for_dianna": false}'::jsonb;

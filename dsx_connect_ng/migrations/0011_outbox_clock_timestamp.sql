ALTER TABLE cp_job_outbox
    ALTER COLUMN created_at SET DEFAULT clock_timestamp(),
    ALTER COLUMN updated_at SET DEFAULT clock_timestamp();

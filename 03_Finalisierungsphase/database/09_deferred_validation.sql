-- Deferred loan consistency runs at transaction commit, after the workflow's
-- SECURITY DEFINER context has ended. Keep this fixed-search-path trigger in
-- the schema owner's context so validation may call its private helper and
-- acquire related loan locks without granting workflow-table writes to web.
BEGIN;
ALTER FUNCTION bookbridge.tg_validate_loan() SECURITY DEFINER;
COMMIT;

-- OpenSpec add-reprocessing-contract: remote runs gain a reprocess origin
-- kind.  The vocabulary trigger is replaced with the extended list; origin
-- rows stay immutable and the kind/reference pairing constraint is unchanged.

DROP TRIGGER IF EXISTS remote_runs_origin_kind_vocabulary;

CREATE TRIGGER remote_runs_origin_kind_vocabulary
BEFORE INSERT ON remote_runs
WHEN NEW.origin_kind IS NOT NULL AND NEW.origin_kind NOT IN ('library_expansion', 'reprocess')
BEGIN
    SELECT RAISE(ABORT, 'unsupported remote run origin kind');
END;

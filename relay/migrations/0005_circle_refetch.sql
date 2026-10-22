-- The admin can tell a site to fetch all the records meant for it again (after a rule or a mapping changed): the counter rises
-- and a site that has seen another value starts again from the beginning (see PROTOCOL.md, "Circle").
ALTER TABLE circle_sites ADD COLUMN refetch INTEGER NOT NULL DEFAULT 0;

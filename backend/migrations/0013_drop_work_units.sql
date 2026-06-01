-- BD-5 u1: remove work units entirely; criteria verification replaces the unit-based
-- tracking model. No data migration — existing specs are re-verified against criteria directly.
DROP TABLE IF EXISTS work_units CASCADE;

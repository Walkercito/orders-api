-- STRICT + CHECK: the database rejects bad rows even if the cleaning step has a bug.
CREATE TABLE orders (
    order_id   INTEGER PRIMARY KEY,
    order_date TEXT    NOT NULL
        CHECK (order_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    customer   TEXT    NOT NULL,
    country    TEXT    NOT NULL,
    product    TEXT    NOT NULL,
    amount     REAL    NOT NULL CHECK (amount > 0),
    status     TEXT    NOT NULL CHECK (status IN ('completed', 'pending', 'cancelled'))
) STRICT;

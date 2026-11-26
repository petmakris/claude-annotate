-- 0042: store invoice amounts as integer cents
ALTER TABLE invoices ADD COLUMN amount_cents BIGINT;
UPDATE invoices SET amount_cents = ROUND(amount * 100);
ALTER TABLE invoices ALTER COLUMN amount_cents SET NOT NULL;
ALTER TABLE invoices DROP COLUMN amount;

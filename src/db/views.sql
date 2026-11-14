-- Sales = completed orders only. Pending and cancelled orders are not revenue.

CREATE VIEW monthly_sales_by_country AS
SELECT
    substr(order_date, 1, 7) AS month,
    country,
    COUNT(*) AS orders_count,
    ROUND(SUM(amount), 2) AS total_amount
FROM orders
WHERE status = 'completed'
GROUP BY month, country
ORDER BY month, country;

CREATE VIEW top_customers AS
SELECT
    customer,
    COUNT(*) AS orders_count,
    ROUND(SUM(amount), 2) AS total_amount
FROM orders
WHERE status = 'completed'
GROUP BY customer
ORDER BY total_amount DESC, customer
LIMIT 10;

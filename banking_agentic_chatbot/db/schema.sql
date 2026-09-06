CREATE DATABASE amana_bank AS PERM = 2000000000;

DATABASE amana_bank;

--------------------------------------------------------------------------------------------
-- 1. Base tables (raw load targets for db/load_data.py)
--------------------------------------------------------------------------------------------

CREATE MULTISET TABLE amana_bank.customers
(
    customer_id           VARCHAR(20)   NOT NULL,
    full_name             VARCHAR(100),
    national_id           VARCHAR(30),
    age                   INTEGER,
    job                   VARCHAR(50),
    marital                VARCHAR(20),
    education              VARCHAR(20),
    has_credit_default    VARCHAR(3),
    balance                DECIMAL(18,2),
    housing_loan          VARCHAR(3),
    personal_loan         VARCHAR(3),
    contact_method        VARCHAR(20),
    contact_day            INTEGER,
    credit_score            INTEGER,
    monthly_income         DECIMAL(18,2),
    loan_history            VARCHAR(20),
    risk_level              VARCHAR(20),
    email                   VARCHAR(100),
    phone                   VARCHAR(30),

    auth_secret_hash       VARCHAR(128)
)
PRIMARY INDEX (customer_id);

CREATE MULTISET TABLE amana_bank.products
(
    product_id                     VARCHAR(20) NOT NULL,
    product_name                   VARCHAR(100),
    category                       VARCHAR(50),
    description                    VARCHAR(1000),
    currency                       VARCHAR(10),
    interest_rate_pct              DECIMAL(9,4),
    term_months                    INTEGER,
    min_balance                    DECIMAL(18,2),
    monthly_fee                    DECIMAL(18,2),
    annual_fee                     DECIMAL(18,2),
    min_income_eligibility         DECIMAL(18,2),
    min_credit_score_eligibility   INTEGER,
    min_age_eligibility            INTEGER,
    max_amount                     DECIMAL(18,2),
    status                         VARCHAR(20),
    launch_date                    DATE
)
PRIMARY INDEX (product_id);

CREATE MULTISET TABLE amana_bank.transactions
(
    transaction_id            VARCHAR(20) NOT NULL,
    customer_id                VARCHAR(20),
    product_id                 VARCHAR(20),
    transaction_date           DATE,
    transaction_type           VARCHAR(50),
    category                    VARCHAR(50),
    direction                   VARCHAR(10),
    amount                      DECIMAL(18,2),
    currency                    VARCHAR(10),
    channel                     VARCHAR(30),
    merchant_or_counterparty    VARCHAR(100),
    description                 VARCHAR(200),
    status                      VARCHAR(20),
    balance_after                DECIMAL(18,2)
)
PRIMARY INDEX (customer_id);

CREATE MULTISET TABLE amana_bank.faqs
(
    faq_id      INTEGER GENERATED ALWAYS AS IDENTITY (START WITH 1 INCREMENT BY 1),
    question    VARCHAR(2000),
    answer      VARCHAR(4000)
)
PRIMARY INDEX (faq_id);



CREATE MULTISET TABLE amana_bank.faq_embeddings
(
    faq_id        INTEGER NOT NULL,
    question      VARCHAR(2000),
    answer        VARCHAR(4000),
    embedding     CLOB  -- JSON array of floats, only used by the legacy Python fallback
)
PRIMARY INDEX (faq_id);

CREATE MULTISET TABLE amana_bank.user_customer_map
(
    db_username    VARCHAR(30) NOT NULL,
    customer_id    VARCHAR(20) NOT NULL
)
PRIMARY INDEX (db_username);

REPLACE VIEW amana_bank.v_my_profile AS
SELECT customer_id, full_name, age, job, marital, education, balance, housing_loan,
       personal_loan, credit_score, monthly_income, loan_history, risk_level, email, phone
FROM amana_bank.customers
WHERE customer_id = (SELECT customer_id FROM amana_bank.user_customer_map WHERE db_username = CURRENT_USER);

REPLACE VIEW amana_bank.v_my_transactions AS
SELECT t.transaction_id, t.product_id, p.product_name, t.transaction_date, t.transaction_type,
       t.category, t.direction, t.amount, t.currency, t.channel, t.merchant_or_counterparty,
       t.description, t.status, t.balance_after
FROM amana_bank.transactions t
LEFT JOIN amana_bank.products p ON p.product_id = t.product_id
WHERE t.customer_id = (SELECT customer_id FROM amana_bank.user_customer_map WHERE db_username = CURRENT_USER);

REPLACE VIEW amana_bank.v_my_products AS
SELECT DISTINCT p.product_id, p.product_name, p.category, p.description, p.currency,
       p.interest_rate_pct, p.term_months, p.status,
       MIN(t.transaction_date) OVER (PARTITION BY p.product_id) AS first_activity_date
FROM amana_bank.transactions t
JOIN amana_bank.products p ON p.product_id = t.product_id
WHERE t.customer_id = (SELECT customer_id FROM amana_bank.user_customer_map WHERE db_username = CURRENT_USER);



GRANT SELECT ON amana_bank.v_my_profile TO PUBLIC;
GRANT SELECT ON amana_bank.v_my_transactions TO PUBLIC;
GRANT SELECT ON amana_bank.v_my_products TO PUBLIC;
GRANT SELECT ON amana_bank.faqs TO PUBLIC;
GRANT SELECT ON amana_bank.faq_embeddings TO PUBLIC;
GRANT SELECT ON amana_bank.products TO PUBLIC;
-- Deliberately NOT granting SELECT on customers/transactions (the base tables) to PUBLIC:
-- those are only ever reachable through the v_my_* views above.

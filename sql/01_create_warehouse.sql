/*==============================================================================================
  MERCHANT SALES & VOUCHER INTELLIGENCE
  Microsoft Fabric Warehouse — DDL for the gold layer

  Target : Fabric Warehouse (T-SQL endpoint)  |  WH_MerchantVoucher
  Author : BI Development
  Notes  : Fabric Warehouse does not enforce PRIMARY KEY / FOREIGN KEY constraints, but it
           DOES use them for query optimisation when declared with NOT ENFORCED. Declaring
           them is therefore worth doing twice over: the optimiser produces better plans,
           and the model is self-documenting for the next engineer.

           Fabric Warehouse currently supports a limited set of data types. VARCHAR(n) is
           used rather than NVARCHAR, and DECIMAL rather than MONEY, in line with that.
==============================================================================================*/

-- ---------------------------------------------------------------------------------------------
-- Schemas: one per medallion layer, so access can be granted per layer.
-- Analysts get SELECT on gold only; engineers get bronze and silver.
-- ---------------------------------------------------------------------------------------------
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'bronze') EXEC('CREATE SCHEMA bronze');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'silver') EXEC('CREATE SCHEMA silver');
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = 'gold')   EXEC('CREATE SCHEMA gold');
GO

/*==============================================================================================
  DIMENSIONS
==============================================================================================*/

DROP TABLE IF EXISTS gold.dim_date;
CREATE TABLE gold.dim_date (
    date_key                INT             NOT NULL,
    [date]                  DATE            NOT NULL,
    [year]                  SMALLINT        NOT NULL,
    [quarter]               TINYINT         NOT NULL,
    quarter_name            VARCHAR(2)      NOT NULL,
    year_quarter            VARCHAR(7)      NOT NULL,
    month_number            TINYINT         NOT NULL,
    month_name              VARCHAR(12)     NOT NULL,
    month_short             VARCHAR(3)      NOT NULL,
    year_month              VARCHAR(7)      NOT NULL,
    month_year_label        VARCHAR(8)      NOT NULL,
    month_year_sort         INT             NOT NULL,
    month_start_date        DATE            NOT NULL,
    month_end_date          DATE            NOT NULL,
    day_of_month            TINYINT         NOT NULL,
    day_of_week             TINYINT         NOT NULL,
    day_name                VARCHAR(10)     NOT NULL,
    day_short               VARCHAR(3)      NOT NULL,
    week_of_year            TINYINT         NOT NULL,
    year_week               VARCHAR(8)      NOT NULL,
    is_weekend              BIT             NOT NULL,
    is_in_fact_window       BIT             NOT NULL,
    relative_month_offset   SMALLINT        NOT NULL,
    is_current_month        BIT             NOT NULL
);
GO
ALTER TABLE gold.dim_date ADD CONSTRAINT PK_dim_date
    PRIMARY KEY NONCLUSTERED (date_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.dim_merchant;
CREATE TABLE gold.dim_merchant (
    merchant_key                VARCHAR(32)     NOT NULL,
    merchant_id                 VARCHAR(10)     NOT NULL,
    merchant_name               VARCHAR(100)    NOT NULL,
    region                      VARCHAR(50)     NOT NULL,
    channel                     VARCHAR(50)     NOT NULL,
    active_status               VARCHAR(20)     NOT NULL,
    is_at_risk                  BIT             NOT NULL,
    account_manager             VARCHAR(50)     NULL,
    onboarded_date              DATE            NULL,
    tenure_months               INT             NULL,
    tenure_band                 VARCHAR(20)     NULL,
    base_monthly_sales_target   DECIMAL(18,2)   NULL,
    annualised_sales_target     DECIMAL(18,2)   NULL,
    merchant_size_band          VARCHAR(20)     NULL
);
GO
ALTER TABLE gold.dim_merchant ADD CONSTRAINT PK_dim_merchant
    PRIMARY KEY NONCLUSTERED (merchant_key) NOT ENFORCED;
ALTER TABLE gold.dim_merchant ADD CONSTRAINT UQ_dim_merchant_id
    UNIQUE NONCLUSTERED (merchant_id) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.dim_voucher_type;
CREATE TABLE gold.dim_voucher_type (
    voucher_type_key    VARCHAR(32)     NOT NULL,
    voucher_type        VARCHAR(50)     NOT NULL,
    voucher_category    VARCHAR(50)     NOT NULL,
    margin_band         VARCHAR(20)     NOT NULL,
    voucher_type_sort   TINYINT         NOT NULL
);
GO
ALTER TABLE gold.dim_voucher_type ADD CONSTRAINT PK_dim_voucher_type
    PRIMARY KEY NONCLUSTERED (voucher_type_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.dim_priority;
CREATE TABLE gold.dim_priority (
    priority_key        VARCHAR(32)     NOT NULL,
    priority            VARCHAR(20)     NOT NULL,
    priority_sort       TINYINT         NOT NULL,
    target_sla_hours    SMALLINT        NOT NULL,
    severity_weight     DECIMAL(4,1)    NOT NULL
);
GO
ALTER TABLE gold.dim_priority ADD CONSTRAINT PK_dim_priority
    PRIMARY KEY NONCLUSTERED (priority_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.dim_ticket_type;
CREATE TABLE gold.dim_ticket_type (
    ticket_type_key     VARCHAR(32)     NOT NULL,
    ticket_type         VARCHAR(60)     NOT NULL,
    ticket_category     VARCHAR(40)     NOT NULL,
    impact_area         VARCHAR(40)     NOT NULL
);
GO
ALTER TABLE gold.dim_ticket_type ADD CONSTRAINT PK_dim_ticket_type
    PRIMARY KEY NONCLUSTERED (ticket_type_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.dim_ticket_status;
CREATE TABLE gold.dim_ticket_status (
    status_key      VARCHAR(32)     NOT NULL,
    [status]        VARCHAR(30)     NOT NULL,
    status_sort     TINYINT         NOT NULL,
    is_open_status  BIT             NOT NULL,
    status_group    VARCHAR(30)     NOT NULL
);
GO
ALTER TABLE gold.dim_ticket_status ADD CONSTRAINT PK_dim_ticket_status
    PRIMARY KEY NONCLUSTERED (status_key) NOT ENFORCED;
GO


/*==============================================================================================
  FACTS
==============================================================================================*/

DROP TABLE IF EXISTS gold.fct_merchant_sales;
CREATE TABLE gold.fct_merchant_sales (
    sales_key           VARCHAR(32)     NOT NULL,
    date_key            INT             NOT NULL,
    merchant_key        VARCHAR(32)     NOT NULL,
    voucher_type_key    VARCHAR(32)     NOT NULL,
    sales_date          DATE            NOT NULL,
    sales_value         DECIMAL(18,2)   NOT NULL,
    transactions        INT             NOT NULL,
    avg_basket_value    DECIMAL(18,4)   NULL,      -- row-level only; never SUM this column
    batch_id            VARCHAR(30)     NOT NULL,
    ingested_at         DATETIME2(3)    NOT NULL
);
GO
ALTER TABLE gold.fct_merchant_sales ADD CONSTRAINT PK_fct_merchant_sales
    PRIMARY KEY NONCLUSTERED (sales_key) NOT ENFORCED;
ALTER TABLE gold.fct_merchant_sales ADD CONSTRAINT FK_fms_date
    FOREIGN KEY (date_key) REFERENCES gold.dim_date (date_key) NOT ENFORCED;
ALTER TABLE gold.fct_merchant_sales ADD CONSTRAINT FK_fms_merchant
    FOREIGN KEY (merchant_key) REFERENCES gold.dim_merchant (merchant_key) NOT ENFORCED;
ALTER TABLE gold.fct_merchant_sales ADD CONSTRAINT FK_fms_vouchertype
    FOREIGN KEY (voucher_type_key) REFERENCES gold.dim_voucher_type (voucher_type_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.fct_voucher_redemptions;
CREATE TABLE gold.fct_voucher_redemptions (
    voucher_id                  VARCHAR(20)     NOT NULL,
    sold_date_key               INT             NOT NULL,
    redeemed_date_key           INT             NULL,   -- NULL until redeemed; INACTIVE rel'ship
    merchant_key                VARCHAR(32)     NOT NULL,
    voucher_type_key            VARCHAR(32)     NOT NULL,
    sold_date                   DATE            NOT NULL,
    redeemed_date               DATE            NULL,
    voucher_value               DECIMAL(18,2)   NOT NULL,
    voucher_count               TINYINT         NOT NULL,
    redeemed_count              TINYINT         NOT NULL,
    redeemed_value              DECIMAL(18,2)   NOT NULL,
    outstanding_value           DECIMAL(18,2)   NOT NULL,
    breakage_value              DECIMAL(18,2)   NOT NULL,
    days_to_redeem              INT             NULL,
    delayed_redemption_count    TINYINT         NOT NULL,
    is_redeemed                 BIT             NOT NULL,
    is_delayed_redemption       BIT             NOT NULL,
    is_expired                  BIT             NOT NULL,
    quality_flag                VARCHAR(30)     NOT NULL,
    batch_id                    VARCHAR(30)     NOT NULL,
    ingested_at                 DATETIME2(3)    NOT NULL
);
GO
ALTER TABLE gold.fct_voucher_redemptions ADD CONSTRAINT PK_fct_voucher_redemptions
    PRIMARY KEY NONCLUSTERED (voucher_id) NOT ENFORCED;
ALTER TABLE gold.fct_voucher_redemptions ADD CONSTRAINT FK_fvr_solddate
    FOREIGN KEY (sold_date_key) REFERENCES gold.dim_date (date_key) NOT ENFORCED;
ALTER TABLE gold.fct_voucher_redemptions ADD CONSTRAINT FK_fvr_merchant
    FOREIGN KEY (merchant_key) REFERENCES gold.dim_merchant (merchant_key) NOT ENFORCED;
GO
-- NOTE: no FK is declared on redeemed_date_key. It is nullable, and a NOT ENFORCED FK on a
-- nullable column adds nothing for the optimiser while implying a constraint that does not
-- hold. The relationship exists in the semantic model as an INACTIVE relationship activated
-- by USERELATIONSHIP inside specific measures.

DROP TABLE IF EXISTS gold.fct_support_tickets;
CREATE TABLE gold.fct_support_tickets (
    ticket_id               VARCHAR(20)     NOT NULL,
    date_key                INT             NOT NULL,
    merchant_key            VARCHAR(32)     NOT NULL,
    ticket_type_key         VARCHAR(32)     NOT NULL,
    priority_key            VARCHAR(32)     NOT NULL,
    status_key              VARCHAR(32)     NOT NULL,
    ticket_date             DATE            NOT NULL,
    ticket_count            TINYINT         NOT NULL,
    resolution_hours        DECIMAL(10,2)   NOT NULL,
    sla_hours               SMALLINT        NOT NULL,   -- SLA in force when raised, see note
    sla_breach_hours        DECIMAL(10,2)   NOT NULL,
    sla_utilisation         DECIMAL(10,4)   NULL,
    sla_breach_count        TINYINT         NOT NULL,
    high_priority_count     TINYINT         NOT NULL,
    open_count              TINYINT         NOT NULL,
    escalated_count         TINYINT         NOT NULL,
    is_sla_breach           BIT             NOT NULL,
    is_high_priority        BIT             NOT NULL,
    is_open                 BIT             NOT NULL,
    is_escalated            BIT             NOT NULL,
    batch_id                VARCHAR(30)     NOT NULL,
    ingested_at             DATETIME2(3)    NOT NULL
);
GO
ALTER TABLE gold.fct_support_tickets ADD CONSTRAINT PK_fct_support_tickets
    PRIMARY KEY NONCLUSTERED (ticket_id) NOT ENFORCED;
ALTER TABLE gold.fct_support_tickets ADD CONSTRAINT FK_fst_date
    FOREIGN KEY (date_key) REFERENCES gold.dim_date (date_key) NOT ENFORCED;
ALTER TABLE gold.fct_support_tickets ADD CONSTRAINT FK_fst_merchant
    FOREIGN KEY (merchant_key) REFERENCES gold.dim_merchant (merchant_key) NOT ENFORCED;
GO

DROP TABLE IF EXISTS gold.fct_merchant_target;
CREATE TABLE gold.fct_merchant_target (
    date_key                    INT             NOT NULL,
    merchant_key                VARCHAR(32)     NOT NULL,
    month_start_date            DATE            NOT NULL,
    monthly_sales_target        DECIMAL(18,2)   NOT NULL,
    base_monthly_sales_target   DECIMAL(18,2)   NOT NULL,
    days_covered                SMALLINT        NOT NULL,
    days_in_month               SMALLINT        NOT NULL
);
GO
-- Periodic snapshot at MONTH grain — coarser than fct_merchant_sales. The two are joined
-- only through the shared dimensions, never to each other.
ALTER TABLE gold.fct_merchant_target ADD CONSTRAINT PK_fct_merchant_target
    PRIMARY KEY NONCLUSTERED (date_key, merchant_key) NOT ENFORCED;
GO


/*==============================================================================================
  ANALYTICS MART & ML OUTPUT
==============================================================================================*/

DROP TABLE IF EXISTS gold.mart_merchant_scorecard;
CREATE TABLE gold.mart_merchant_scorecard (
    merchant_key                VARCHAR(32)     NOT NULL,
    merchant_name               VARCHAR(100)    NOT NULL,
    region                      VARCHAR(50)     NOT NULL,
    channel                     VARCHAR(50)     NOT NULL,
    account_manager             VARCHAR(50)     NULL,
    active_status               VARCHAR(20)     NOT NULL,
    merchant_size_band          VARCHAR(20)     NULL,
    total_sales                 DECIMAL(18,2)   NULL,
    total_transactions          INT             NULL,
    avg_basket_value            DECIMAL(18,4)   NULL,
    latest_month_sales          DECIMAL(18,2)   NULL,
    prior_month_sales           DECIMAL(18,2)   NULL,
    mom_change                  DECIMAL(10,6)   NULL,
    sales_vs_prior_3m_avg       DECIMAL(10,6)   NULL,
    last3_vs_first3             DECIMAL(10,6)   NULL,
    sales_target                DECIMAL(18,2)   NULL,
    target_attainment           DECIMAL(10,6)   NULL,
    target_attainment_index     DECIMAL(10,6)   NULL,
    vouchers_sold               INT             NULL,
    vouchers_redeemed           INT             NULL,
    redemption_rate             DECIMAL(10,6)   NULL,
    avg_days_to_redeem          DECIMAL(10,4)   NULL,
    delayed_redemption_rate     DECIMAL(10,6)   NULL,
    outstanding_value           DECIMAL(18,2)   NULL,
    tickets                     INT             NULL,
    avg_resolution_hours        DECIMAL(10,4)   NULL,
    sla_breach_rate             DECIMAL(10,6)   NULL,
    high_priority_tickets       INT             NULL,
    open_tickets                INT             NULL,
    tickets_per_1k_txn          DECIMAL(10,4)   NULL,
    tickets_vs_prior_3m_avg     DECIMAL(10,6)   NULL,
    health_score                DECIMAL(5,1)    NULL,
    health_band                 VARCHAR(20)     NULL,
    sales_rank                  INT             NULL,
    transaction_rank            INT             NULL,
    sales_share                 DECIMAL(10,6)   NULL,
    cumulative_share            DECIMAL(10,6)   NULL,
    pareto_band                 VARCHAR(30)     NULL,
    revenue_at_risk_annualised  DECIMAL(18,2)   NULL
);
GO
ALTER TABLE gold.mart_merchant_scorecard ADD CONSTRAINT PK_mart_scorecard
    PRIMARY KEY NONCLUSTERED (merchant_key) NOT ENFORCED;
GO

-- Written back by the Fabric notebook so Power BI reads predictions as ordinary columns
-- rather than calling a model at query time.
DROP TABLE IF EXISTS gold.ml_anomaly_scores;
CREATE TABLE gold.ml_anomaly_scores (
    merchant_key        VARCHAR(32)     NOT NULL,
    merchant_name       VARCHAR(100)    NOT NULL,
    year_month          VARCHAR(7)      NOT NULL,
    anomaly_score       DECIMAL(10,6)   NOT NULL,
    is_anomaly          BIT             NOT NULL,
    explanation         VARCHAR(500)    NULL,
    model_version       VARCHAR(30)     NOT NULL,
    scored_at           DATETIME2(3)    NOT NULL
);
GO

DROP TABLE IF EXISTS gold.ml_sales_forecast;
CREATE TABLE gold.ml_sales_forecast (
    forecast_date       DATE            NOT NULL,
    forecast_value      DECIMAL(18,2)   NOT NULL,
    lower_80            DECIMAL(18,2)   NOT NULL,
    upper_80            DECIMAL(18,2)   NOT NULL,
    lower_95            DECIMAL(18,2)   NOT NULL,
    upper_95            DECIMAL(18,2)   NOT NULL,
    model_version       VARCHAR(30)     NOT NULL,
    scored_at           DATETIME2(3)    NOT NULL
);
GO

PRINT 'Gold layer DDL complete: 6 dimensions, 4 facts, 1 mart, 2 ML output tables.';

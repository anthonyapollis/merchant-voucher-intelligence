/* ===========================================================================
   01_warehouse_ddl.sql
   ---------------------------------------------------------------------------
   Star schema DDL for wh_merchant_analytics (Fabric Warehouse).

   Use this path when the consumer needs T-SQL, stored procedures or row-level
   security enforced in the warehouse. The Lakehouse path (nb_03) produces the
   same tables as Delta for Direct Lake; the two are alternatives, not layers -
   pick one per workspace and say which in the README.

   Fabric Warehouse notes that shape the DDL below:
     * PRIMARY KEY / FOREIGN KEY are supported only as NOT ENFORCED. They are
       still worth declaring: the optimiser uses them, and they document intent
       for anyone reading the schema cold.
     * There is no IDENTITY. Surrogate keys are deterministic - yyyymmdd for
       dates, the natural business key elsewhere - which also makes reloads
       idempotent.
     * VARCHAR must be sized. Oversized string columns inflate the estimated
       row width and push the optimiser into worse join strategies.
   =========================================================================== */

CREATE SCHEMA gold;
GO

/* ------------------------------------------------------------- dimensions -- */

CREATE TABLE gold.DimDate (
    DateKey             INT             NOT NULL,
    [Date]              DATE            NOT NULL,
    [Year]              SMALLINT        NOT NULL,
    QuarterNumber       TINYINT         NOT NULL,
    [Quarter]           VARCHAR(2)      NOT NULL,
    MonthNumber         TINYINT         NOT NULL,
    MonthName           VARCHAR(12)     NOT NULL,
    MonthShort          VARCHAR(3)      NOT NULL,
    MonthYear           VARCHAR(8)      NOT NULL,
    MonthYearSort       INT             NOT NULL,
    [Day]               TINYINT         NOT NULL,
    DayName             VARCHAR(9)      NOT NULL,
    DayOfWeek           TINYINT         NOT NULL,
    IsWeekend           TINYINT         NOT NULL,
    WeekOfYear          TINYINT         NOT NULL,
    WeekStartDate       DATE            NOT NULL,
    MonthStartDate      DATE            NOT NULL,
    MonthEndDate        DATE            NOT NULL,
    CONSTRAINT PK_DimDate PRIMARY KEY NONCLUSTERED (DateKey) NOT ENFORCED
);
GO

CREATE TABLE gold.DimMerchant (
    MerchantKey             VARCHAR(10)     NOT NULL,
    Merchant                VARCHAR(60)     NOT NULL,
    Region                  VARCHAR(30)     NOT NULL,
    Channel                 VARCHAR(20)     NOT NULL,
    ActiveStatus            VARCHAR(12)     NOT NULL,
    AccountManager          VARCHAR(40)     NULL,
    OnboardedDate           DATE            NULL,
    TenureMonths            SMALLINT        NULL,
    TenureBand              VARCHAR(14)     NULL,
    BaseMonthlySalesTarget  DECIMAL(18, 2)  NULL,
    CONSTRAINT PK_DimMerchant PRIMARY KEY NONCLUSTERED (MerchantKey) NOT ENFORCED
);
GO

CREATE TABLE gold.DimVoucherType (
    VoucherTypeKey  VARCHAR(20) NOT NULL,
    VoucherType     VARCHAR(20) NOT NULL,
    SettlementModel VARCHAR(22) NOT NULL,
    CONSTRAINT PK_DimVoucherType PRIMARY KEY NONCLUSTERED (VoucherTypeKey) NOT ENFORCED
);
GO

CREATE TABLE gold.DimTicketType (
    TicketTypeKey   VARCHAR(30) NOT NULL,
    TicketType      VARCHAR(30) NOT NULL,
    TicketCategory  VARCHAR(12) NOT NULL,
    CONSTRAINT PK_DimTicketType PRIMARY KEY NONCLUSTERED (TicketTypeKey) NOT ENFORCED
);
GO

/* SLAHours arrives on every ticket row but is a fixed property of the priority
   tier (verified one-to-one). It is promoted here so an SLA policy change is a
   one-row update rather than a fact rewrite. */
CREATE TABLE gold.DimPriority (
    PriorityKey     VARCHAR(10) NOT NULL,
    Priority        VARCHAR(10) NOT NULL,
    PrioritySort    TINYINT     NOT NULL,
    SLATargetHours  INT         NOT NULL,
    CONSTRAINT PK_DimPriority PRIMARY KEY NONCLUSTERED (PriorityKey) NOT ENFORCED
);
GO

/* ------------------------------------------------------------------ facts -- */

CREATE TABLE gold.FactMerchantSales (
    DateKey         INT             NOT NULL,
    MerchantKey     VARCHAR(10)     NOT NULL,
    VoucherTypeKey  VARCHAR(20)     NOT NULL,
    SalesValue      DECIMAL(18, 2)  NOT NULL,
    Transactions    INT             NOT NULL,
    CONSTRAINT FK_Sales_Date     FOREIGN KEY (DateKey)        REFERENCES gold.DimDate (DateKey) NOT ENFORCED,
    CONSTRAINT FK_Sales_Merchant FOREIGN KEY (MerchantKey)    REFERENCES gold.DimMerchant (MerchantKey) NOT ENFORCED,
    CONSTRAINT FK_Sales_Voucher  FOREIGN KEY (VoucherTypeKey) REFERENCES gold.DimVoucherType (VoucherTypeKey) NOT ENFORCED
);
GO

/* Two date keys, one calendar. SoldDateKey drives the active relationship;
   RedeemedDateKey is the role-playing second key the semantic model activates
   with USERELATIONSHIP. RedeemedDateKey is NULL when the voucher has not been
   redeemed - that null is information, not a defect. */
CREATE TABLE gold.FactVoucherRedemptions (
    VoucherID           VARCHAR(12)     NOT NULL,
    SoldDateKey         INT             NOT NULL,
    RedeemedDateKey     INT             NULL,
    MerchantKey         VARCHAR(10)     NOT NULL,
    VoucherTypeKey      VARCHAR(20)     NOT NULL,
    VoucherValue        DECIMAL(18, 2)  NOT NULL,
    IsRedeemed          TINYINT         NOT NULL,
    DaysToRedeem        INT             NULL,
    IsDelayedRedemption TINYINT         NULL,
    CONSTRAINT PK_Redemptions PRIMARY KEY NONCLUSTERED (VoucherID) NOT ENFORCED,
    CONSTRAINT FK_Red_SoldDate FOREIGN KEY (SoldDateKey)    REFERENCES gold.DimDate (DateKey) NOT ENFORCED,
    CONSTRAINT FK_Red_Merchant FOREIGN KEY (MerchantKey)    REFERENCES gold.DimMerchant (MerchantKey) NOT ENFORCED,
    CONSTRAINT FK_Red_Voucher  FOREIGN KEY (VoucherTypeKey) REFERENCES gold.DimVoucherType (VoucherTypeKey) NOT ENFORCED
);
GO

CREATE TABLE gold.FactSupportTickets (
    TicketID        VARCHAR(10)     NOT NULL,
    DateKey         INT             NOT NULL,
    MerchantKey     VARCHAR(10)     NOT NULL,
    TicketTypeKey   VARCHAR(30)     NOT NULL,
    PriorityKey     VARCHAR(10)     NOT NULL,
    ResolutionHours DECIMAL(10, 2)  NULL,
    SLAHours        INT             NOT NULL,
    [Status]        VARCHAR(20)     NOT NULL,
    IsSLABreach     TINYINT         NOT NULL,
    IsOpen          TINYINT         NOT NULL,
    CONSTRAINT PK_Tickets PRIMARY KEY NONCLUSTERED (TicketID) NOT ENFORCED,
    CONSTRAINT FK_Tick_Date     FOREIGN KEY (DateKey)       REFERENCES gold.DimDate (DateKey) NOT ENFORCED,
    CONSTRAINT FK_Tick_Merchant FOREIGN KEY (MerchantKey)   REFERENCES gold.DimMerchant (MerchantKey) NOT ENFORCED,
    CONSTRAINT FK_Tick_Type     FOREIGN KEY (TicketTypeKey) REFERENCES gold.DimTicketType (TicketTypeKey) NOT ENFORCED,
    CONSTRAINT FK_Tick_Priority FOREIGN KEY (PriorityKey)   REFERENCES gold.DimPriority (PriorityKey) NOT ENFORCED
);
GO

/* ------------------------------------------------- analytical output tables */

CREATE TABLE gold.FactAnomaly (
    AnomalyID       VARCHAR(40)     NOT NULL,
    [Date]          DATE            NOT NULL,
    MerchantKey     VARCHAR(10)     NULL,   -- null for region/voucher-type scope
    Merchant        VARCHAR(60)     NOT NULL,
    Region          VARCHAR(30)     NULL,
    Measure         VARCHAR(40)     NOT NULL,
    ActualValue     DECIMAL(18, 2)  NOT NULL,
    ExpectedValue   DECIMAL(18, 2)  NOT NULL,
    Score           DECIMAL(10, 2)  NOT NULL,
    ScoreType       VARCHAR(16)     NOT NULL,
    DeviationPct    DECIMAL(10, 2)  NULL,
    Direction       VARCHAR(16)     NOT NULL,
    Severity        VARCHAR(8)      NOT NULL,
    CONSTRAINT PK_Anomaly PRIMARY KEY NONCLUSTERED (AnomalyID) NOT ENFORCED
);
GO

CREATE TABLE gold.InsightNarrative (
    MerchantKey         VARCHAR(10)     NOT NULL,
    Merchant            VARCHAR(60)     NOT NULL,
    Region              VARCHAR(30)     NOT NULL,
    Channel             VARCHAR(20)     NOT NULL,
    Headline            VARCHAR(20)     NOT NULL,
    ActionFlag          VARCHAR(14)     NOT NULL,
    SalesMoMPct         DECIMAL(10, 2)  NULL,
    TransactionsMoMPct  DECIMAL(10, 2)  NULL,
    AvgBasketMoMPct     DECIMAL(10, 2)  NULL,
    TicketsThisMonth    INT             NOT NULL,
    TicketsPrevMonth    INT             NOT NULL,
    Narrative           VARCHAR(1000)   NOT NULL,
    CONSTRAINT PK_Narrative PRIMARY KEY NONCLUSTERED (MerchantKey) NOT ENFORCED
);
GO

CREATE TABLE gold.DimMerchantSegment (
    MerchantKey             VARCHAR(10)     NOT NULL,
    Merchant                VARCHAR(60)     NOT NULL,
    Segment                 VARCHAR(30)     NOT NULL,
    SegmentID               TINYINT         NOT NULL,
    SegmentProfile          VARCHAR(300)    NULL,
    PCA1                    DECIMAL(10, 4)  NULL,
    PCA2                    DECIMAL(10, 4)  NULL,
    HealthScore             DECIMAL(5, 1)   NOT NULL,
    RiskTier                VARCHAR(10)     NOT NULL,
    GrowthSlopePct          DECIMAL(10, 3)  NULL,
    TargetAttainmentPct     DECIMAL(10, 2)  NULL,
    CONSTRAINT PK_Segment PRIMARY KEY NONCLUSTERED (MerchantKey) NOT ENFORCED
);
GO

CREATE TABLE gold.FactSalesForecast (
    [Date]              DATE            NOT NULL,
    Scope               VARCHAR(20)     NOT NULL,
    ForecastSalesValue  DECIMAL(18, 2)  NOT NULL,
    LowerBound          DECIMAL(18, 2)  NOT NULL,
    UpperBound          DECIMAL(18, 2)  NOT NULL
);
GO

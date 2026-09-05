# WhyLedger

### AI-Powered Financial Change Explanation Agent

WhyLedger turns raw financial changes into clear, evidence-backed explanations.

Instead of simply telling a finance team that **“Revenue increased 18%,”** WhyLedger investigates the underlying financial data and explains **what changed, why it changed, and which transactions or business drivers caused the movement.**

---

## Problem Statement

Financial teams spend significant time every month comparing financial results across periods and investigating why numbers changed.

Traditional dashboards can tell analysts:

> Enterprise Revenue increased 31.7%.

But they usually cannot explain:

> Why did it increase? Which customers drove the change? Which transactions support that conclusion? Has this happened before?

Answering these questions requires analysts to manually move between spreadsheets, transaction exports, dashboards, and historical reports.

The challenge is not simply detecting a financial variance. It is **turning that variance into a trustworthy explanation backed by real financial evidence.**

---

## Our Solution

WhyLedger is an AI-powered financial investigation agent that automatically analyzes financial changes across reporting periods.

Users upload:

- Monthly financial summary data
- Transaction-level financial data

WhyLedger then:

```text
Compares financial periods
        ↓
Detects meaningful variances
        ↓
Ranks the most important changes
        ↓
Investigates potential drivers
        ↓
Finds supporting transactions
        ↓
Retrieves relevant historical context
        ↓
Generates an evidence-backed explanation
```

For example, instead of:

> Enterprise Revenue increased 31.7%.

WhyLedger can explain:

> Enterprise Revenue increased $260K, or 31.7%, compared with the previous period. Acme, Globex, and Umbrella were the largest contributors to the increase, with the movement concentrated among existing enterprise customers.

Every financial number in the explanation comes from the deterministic analytics engine rather than being calculated by the LLM.

---

## Key Features

### 1. Automated Period Comparison

WhyLedger compares financial accounts across two periods and calculates:

- Previous-period value
- Current-period value
- Absolute change
- Percentage change

This creates the foundation for identifying financially meaningful movements.

### 2. Intelligent Variance Ranking

Not every percentage change matters.

WhyLedger considers both **absolute dollar movement and percentage movement** to surface the changes most likely to deserve investigation.

### 3. Automatic Driver Analysis

For each important variance, WhyLedger investigates available business dimensions such as:

```text
Customer
Vendor
Product
Department
Region
```

For example:

```text
Enterprise Revenue       +$260K

Acme                      +$60K
Globex                    +$42K
Umbrella                  +$31K
Other                     +$127K
```

This allows the system to move from identifying **what changed** to understanding **what drove the change**.

### 4. Transaction-Level Evidence

Users can drill down from an explanation directly into the transactions supporting it.

WhyLedger maintains references between:

```text
Variance → Driver → Transactions
```

This makes AI-generated explanations traceable and auditable.

### 5. Evidence-Grounded AI Explanations

The AI layer converts structured financial analysis into concise explanations covering:

```text
What changed?
Why did it change?
What were the largest drivers?
Is there relevant historical context?
```

The LLM is deliberately separated from financial calculations.

It can reason about **what to investigate and how to explain it**, but it cannot independently calculate totals, percentages, or contributions.

### 6. Financial Memory

WhyLedger remembers explanations that users confirm.

For example, during one analysis:

> Sales commissions increased because of quarter-end commission payments.

If the user confirms this explanation, WhyLedger stores that context.

When commissions increase in a later quarter, the system can retrieve the previous explanation and determine whether the **current transaction data supports the same pattern**.

Historical memory provides context but never overrides current financial evidence.

---

## Tech Stack

### Backend

```text
Python
FastAPI
DuckDB
Pandas / Polars
Pydantic
```

### AI & Investigation Layer

```text
LLM-based investigation agent
Structured tool calling
Evidence-grounded generation
Historical context retrieval
```

### Frontend

```text
Next.js
TypeScript
Tailwind CSS
shadcn/ui
Recharts
```

### Persistence

```text
SQLite
```

### Data

```text
CSV
DuckDB
```

---

## How It Works

WhyLedger separates **financial computation** from **AI reasoning**.

```text
                   ┌─────────────────┐
                   │    Frontend     │
                   │    Next.js      │
                   └────────┬────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │     FastAPI     │
                   └────────┬────────┘
                            │
                            ▼
              ┌──────────────────────────┐
              │ AI Investigation Layer   │
              │                          │
              │ • Decide what to inspect│
              │ • Interpret drivers     │
              │ • Retrieve memory       │
              │ • Generate explanation  │
              └────────────┬─────────────┘
                           │
                           ▼
              ┌──────────────────────────┐
              │ Financial Analytics      │
              │ Engine                   │
              │                          │
              │ • Period comparison     │
              │ • Variance ranking      │
              │ • Driver calculations   │
              │ • Transaction retrieval │
              └────────────┬─────────────┘
                           │
                  ┌────────┴────────┐
                  ▼                 ▼
              DuckDB / CSV       SQLite
                                Memory
```

The workflow begins when the user selects two financial periods.

The analytics engine calculates account-level changes and identifies the most important variances.

The AI investigation layer then requests breakdowns across available dimensions, identifies meaningful contributors, retrieves supporting transactions, and checks for relevant confirmed historical explanations.

Finally, the LLM converts this structured evidence into a concise financial explanation.

---

## How to Run / Use It

### 1. Clone the Repository

```bash
git clone <repository-url>
cd whyledger
```

### 2. Start the Backend

```bash
cd backend

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

uvicorn app.main:app --reload
```

The backend will run locally on port `8000`.

### 3. Start the Frontend

Open another terminal:

```bash
cd frontend

npm install
npm run dev
```

The frontend will run locally on port `3000`.

### 4. Open WhyLedger

Open the frontend in your browser and upload:

```text
Monthly Summary CSV
Transaction CSV
```

Select:

```text
Current Period
Comparison Period
```

Then click **Analyze**.

### 5. Investigate a Variance

The overview displays the largest financial changes.

Select a variance to see:

- Absolute and percentage movement
- Largest drivers
- AI-generated explanation
- Supporting transactions
- Relevant historical context

### 6. Confirm an Explanation

When an explanation correctly describes a recurring financial pattern, confirm it.

WhyLedger stores that context and can retrieve it during future analyses while still validating the explanation against current transaction data.

---

## Demo Dataset

WhyLedger includes a fictional B2B SaaS company:

### Northstar AI

The dataset contains approximately six months of financial data across accounts such as:

```text
Enterprise Revenue
SMB Revenue
Usage Revenue
Payroll
Cloud Infrastructure
Sales Commissions
Marketing
Legal
```

Transaction data contains dimensions including:

```text
Customer
Vendor
Department
Product
```

The dataset contains several intentionally seeded scenarios that demonstrate the system's investigation capabilities.

### Enterprise Revenue Growth

Enterprise revenue increases materially, with several large customers responsible for most of the movement.

WhyLedger identifies those customers and links the explanation to their underlying transactions.

### One-Off Legal Expense

Legal expenses suddenly increase because of a large invoice.

WhyLedger identifies the vendor and transaction responsible rather than simply reporting that legal expenses increased.

### Recurring Commission Pattern

Sales commissions increase near quarter-end.

During the first analysis, the user confirms that the movement represents a quarter-end commission pattern.

During a later analysis, WhyLedger retrieves that context and verifies whether current transactions show the same behavior.

---

## What Makes WhyLedger Different

Most financial dashboards stop at:

> **What changed?**

WhyLedger continues the investigation:

```text
WHAT changed?
      ↓
WHY did it change?
      ↓
WHO or WHAT drove it?
      ↓
WHICH transactions prove it?
      ↓
HAS this happened before?
```

This creates a financial analysis system where AI explanations remain grounded in deterministic financial calculations and traceable transaction evidence.

---

## Trust and Explainability

Financial analysis requires more than fluent AI-generated text.

For this reason, WhyLedger follows one important architectural rule:

> **The LLM reasons about financial evidence. It does not create the financial evidence.**

The analytics engine is responsible for:

```text
Totals
Period changes
Percentages
Driver contributions
Transaction amounts
```

The AI layer is responsible for:

```text
Choosing what to investigate
Interpreting calculated drivers
Connecting relevant historical context
Producing concise explanations
```

This separation reduces hallucinated financial figures and makes every explanation easier to verify.

---

## Future Improvements

The hackathon version deliberately focuses on making the core investigation workflow reliable.

Future extensions could include:

- Direct ERP and accounting-platform integrations
- Budget vs. actual analysis
- Forecast variance explanations
- Automated monthly close commentary
- Natural-language financial investigation
- More sophisticated anomaly detection
- Role-based access and approval workflows
- Cross-company financial benchmarking

---

## The Goal

WhyLedger transforms financial reporting from:

> **“Revenue increased 18%.”**

into:

> **“Revenue increased 18%, primarily driven by growth among enterprise customers. Acme, Globex, and Umbrella accounted for the majority of the increase, with supporting transactions showing the movement was concentrated among existing enterprise accounts.”**

Instead of forcing analysts to manually investigate every number, WhyLedger helps them move directly from **financial change → evidence → explanation.**

# 🐋 WhaleWatch

## AI-Powered SaaS Revenue Concentration Risk Agent

**Don't just track revenue. Track the whales driving it.**

WhaleWatch helps SaaS companies understand whether their revenue growth is actually healthy — or dangerously dependent on a small number of customers.

A company can report rising monthly recurring revenue while quietly becoming more fragile. WhaleWatch looks beyond total revenue, investigates the customers behind the movement, identifies **"whales,"** surfaces hidden churn, and explains the real financial story.

Instead of simply reporting:

> **MRR increased 5% this month.**

WhaleWatch can explain:

> **MRR increased 5%, but the growth was entirely driven by one large customer. Meanwhile, 20 smaller accounts churned. The largest customer now represents 45% of total MRR, creating significant concentration risk.**

---

# Problem Statement

Traditional SaaS dashboards focus heavily on topline metrics such as:

- Total MRR
- Revenue growth
- New subscriptions
- Expansion revenue

These numbers can look healthy while hiding serious business risk.

Imagine a restaurant generating **$10,000 per week**, but **$8,000 comes from one family**. The restaurant appears successful, but if that family stops visiting, revenue collapses.

That is **concentration risk**.

The same problem exists in SaaS businesses.

A company might report:

> **Revenue increased 10%.**

But underneath that growth:

- One large customer may account for most of the increase.
- Smaller customers may be quietly churning.
- Revenue may be becoming increasingly concentrated.
- The business may be more fragile than the headline number suggests.

The real question isn't just:

> **Is revenue growing?**

It is:

> **How durable is that growth, who is driving it, and what happens if the largest customers leave?**

---

# Our Solution

WhaleWatch is an **AI-powered concentration risk agent** that analyzes SaaS revenue at the individual customer level.

The system investigates revenue quality through four main steps:

**Establish revenue baseline**

↓

**Identify customer whales**

↓

**Detect hidden losses and churn**

↓

**Explain the true revenue story**

Rather than treating total MRR as the final answer, WhaleWatch decomposes the number into the customer behavior underneath it.

For example, this might initially look very strong:

**Total MRR:** $34.55M  
**Month-over-month growth:** +20.8%

But WhaleWatch might discover:

**Largest customer exposure:** 34.7% of MRR  
**Gross MRR lost:** $830K  
**Potential non-renewal impact:** $12M  
**Underlying MRR:** Much weaker after excluding the largest account

The result is a clearer view of whether revenue growth is **diversified, durable, or dangerously concentrated.**

---

# Key Features

## 1. Revenue Baseline Analysis

WhaleWatch calculates the core metrics required to understand the portfolio:

- Total MRR
- Month-over-month MRR growth
- Expansion revenue
- Revenue losses
- Opening and closing MRR
- Customer count

This establishes **what changed** before the agent investigates **why it changed**.

---

## 2. Whale Detection

The agent identifies customers responsible for a disproportionate share of revenue.

It calculates:

- Largest customer exposure
- Top 5 customer exposure
- Customer-level MRR contribution
- Customer-level revenue movement

For example:

> **Account 008593 represents 34.7% of total MRR.**

This immediately surfaces situations where the behavior of a single customer could materially affect the entire business.

---

## 3. Revenue Concentration Analysis

WhaleWatch measures how distributed revenue is across the customer base.

The dashboard provides:

- Top 1 exposure
- Top 5 exposure
- Customer concentration distribution
- Portfolio diversification
- HHI concentration score

The **Herfindahl-Hirschman Index (HHI)** provides an additional quantitative measure of how concentrated the customer portfolio is.

This helps distinguish **healthy diversified growth** from **growth dominated by a small number of customers**.

---

## 4. Hidden Loss Detection

Topline growth can hide deterioration elsewhere.

WhaleWatch scans customer-level revenue movements to identify:

- Full customer churn
- Partial contraction
- Non-renewals
- Declining accounts
- Negative MRR movement
- Silent losses among smaller customers

For example:

**Large customer expansion:** +$7.4M  
**Customer losses:** -$830K  
**Closing MRR:** $34.55M

A normal dashboard celebrates the closing number.

WhaleWatch investigates what happened underneath it.

---

## 5. MRR Movement Bridge

WhaleWatch decomposes monthly MRR movement into:

**Opening MRR + Expansion - Losses = Closing MRR**

This allows users to understand exactly how the company moved from one month's revenue level to the next.

---

## 6. Revenue Quality Analysis

WhaleWatch compares:

**Total MRR**

against:

**MRR excluding the largest customer**

This answers an important question:

> **Is the underlying business actually growing, or is one whale making the portfolio look healthier than it really is?**

The system therefore distinguishes between **headline growth** and **underlying diversified growth**.

---

## 7. Customer Regime Classification

WhaleWatch classifies customers based on their recent revenue behavior:

- 🟢 Growth
- 🔵 Stable
- 🔴 Decline

This provides a portfolio-level view of customer health.

A company may have increasing total MRR while a significant percentage of its individual customers are declining.

---

## 8. Industry Distribution

WhaleWatch analyzes how the customer portfolio is distributed across industries such as:

- SaaS
- Consulting
- EdTech
- Energy
- Health
- Logistics
- Media
- FinTech
- Retail
- Manufacturing

This extends concentration analysis beyond individual customers into the broader composition of the portfolio.

---

## 9. Executive Concentration Readout

WhaleWatch translates raw analytics into a concise executive story.

For example:

### Baseline

MRR reached **$34.55M**, up **20.8% month over month**.

### Largest Account

Account 008593 increased by approximately **$3.5M** and now represents **34.7% of MRR**.

### Hidden Losses

Approximately **$830K of negative MRR movement** occurred elsewhere in the portfolio.

### The Real Story

Revenue is growing, but the company is becoming increasingly dependent on a small number of customers, creating material downside risk if a major account does not renew.

---

## 10. Whale AI Agent

WhaleWatch includes an AI agent — **Mr. Whale** — that allows users to investigate the portfolio conversationally.

Users can ask:

- "How concentrated is our revenue?"
- "Who is our largest customer?"
- "What caused revenue to increase this month?"
- "Are we losing smaller customers?"
- "What happens if our largest account churns?"
- "Is our growth actually diversified?"
- "Which accounts are declining?"
- "How much MRR is at risk?"

The agent answers using analytics generated from the underlying customer data rather than inventing financial values.

---

# Tech Stack

## Backend

- Python
- FastAPI
- Pandas / Polars
- DuckDB
- Pydantic

## AI Layer

- LLM-powered revenue investigation agent
- Structured analytics tools
- Evidence-grounded responses
- Customer concentration reasoning

## Frontend

- Next.js
- TypeScript
- Tailwind CSS
- shadcn/ui
- Recharts

## Data & Persistence

- CSV
- DuckDB
- SQLite

---

# How It Works

WhaleWatch separates **deterministic financial calculations** from **AI interpretation**.

### 1. Customer Revenue Data

The application ingests customer-level SaaS revenue data across multiple periods.

↓

### 2. Revenue Analytics Engine

The deterministic analytics engine:

- Calculates MRR
- Compares periods
- Detects whales
- Calculates customer exposure
- Calculates HHI
- Detects churn and contraction
- Builds the MRR movement bridge

↓

### 3. Whale Agent

The AI layer:

- Investigates revenue movements
- Determines which customer changes matter
- Interprets concentration risk
- Answers natural-language questions
- Generates executive summaries

↓

### 4. WhaleWatch Dashboard

The frontend presents:

- Revenue quality
- Customer concentration
- MRR movement
- Customer regimes
- Industry distribution
- Executive insights
- AI-powered investigation

---

# Agent Workflow

For every portfolio analysis, WhaleWatch follows a simple investigation process.

### Step 1 — Establish the Baseline

Calculate opening MRR, closing MRR, month-over-month growth, and customer-level MRR.

Example:

> **MRR increased from $28.6M to $34.5M.**

### Step 2 — Hunt for Whales

Determine which customers caused the movement.

Example:

> **Account 008593 increased approximately $3.5M and now represents 34.7% of MRR.**

### Step 3 — Search for Hidden Losses

Analyze the rest of the customer base for:

- Churn
- Contraction
- Declining accounts
- Non-renewals
- Negative revenue movement

This prevents large customer expansion from hiding deterioration elsewhere.

### Step 4 — Deliver the Real Story

The Whale Agent combines verified analytics into an executive-level explanation.

Instead of:

> **MRR increased 20.8%.**

WhaleWatch can explain:

> **MRR increased 20.8% month over month, but a substantial portion of the growth was driven by the largest customer, which now represents 34.7% of total MRR. At the same time, the wider portfolio generated approximately $830K in negative revenue movement. Growth remains positive, but customer concentration creates material downside risk.**

---

# How to Run / Use It

## 1. Clone the Repository

`git clone <repository-url>`

`cd whalewatch`

## 2. Start the Backend

`cd backend`

Create a virtual environment:

`python -m venv venv`

Activate it on macOS/Linux:

`source venv/bin/activate`

Or on Windows:

`venv\Scripts\activate`

Install dependencies:

`pip install -r requirements.txt`

Start FastAPI:

`uvicorn app.main:app --reload`

The backend will run on:

`http://localhost:8000`

## 3. Start the Frontend

Open another terminal:

`cd frontend`

Install dependencies:

`npm install`

Start the development server:

`npm run dev`

The frontend will run on:

`http://localhost:3000`

## 4. Load Revenue Data

Load the customer-level SaaS revenue dataset.

The dataset contains information such as:

- Customer / Account ID
- Period
- MRR
- Industry
- Customer status
- Revenue movement

## 5. Open the Dashboard

WhaleWatch automatically calculates:

- Total MRR
- MRR excluding the largest account
- Top 1 exposure
- Top 5 exposure
- Gross MRR loss
- HHI concentration score

The dashboard then visualizes:

- Revenue quality
- Customer concentration
- MRR movement bridge
- Company regime state
- Industry distribution
- Executive concentration readout

## 6. Ask Mr. Whale

Use the Whale Agent panel to investigate the portfolio conversationally.

For example:

> **Why did MRR increase?**

The agent traces the movement back to customer-level data and explains whether that growth is diversified or concentrated.

---

# Example Scenario

Consider a SaaS company with:

**Previous MRR:** $100,000  
**Current MRR:** $105,000  
**Growth:** +5%

A traditional dashboard reports:

> **Revenue increased 5%.**

WhaleWatch investigates further and discovers:

**Client X expansion:** +$15,000  
**20 customer churns:** -$10,000  
**Net movement:** +$5,000

Client X now represents:

> **45% of total company MRR**

WhaleWatch therefore reports:

> **Revenue increased 5%, but the growth was entirely driven by Client X. Meanwhile, 20 smaller customers churned. Client X now represents 45% of total MRR, meaning the company's underlying customer base is shrinking while concentration risk is increasing.**

That is the difference between measuring **revenue growth** and measuring **revenue quality**.

---

# What Makes WhaleWatch Different?

Most revenue dashboards answer:

> **How much revenue do we have?**

WhaleWatch continues the investigation:

**How much revenue do we have?**

↓

**Where did the growth come from?**

↓

**Which customers control the revenue?**

↓

**What losses are being hidden?**

↓

**How concentrated is the portfolio?**

↓

**What happens if a whale leaves?**

The goal is not simply to track revenue.

The goal is to understand **how fragile that revenue is.**

---

# Trust and Explainability

WhaleWatch follows one critical architectural rule:

> **The LLM interprets financial evidence. It does not invent the financial evidence.**

The deterministic analytics engine calculates:

- MRR
- Revenue growth
- Customer contribution
- Top-N exposure
- HHI
- Expansion
- Contraction
- Churn
- Portfolio losses

The Whale Agent handles:

- Investigation
- Interpretation
- Risk explanation
- Executive summaries
- Natural-language Q&A

This separation reduces the risk of hallucinated financial numbers and keeps the AI grounded in actual customer data.

---

# Why It Matters

Revenue concentration is often invisible in headline financial reporting.

A SaaS company can simultaneously have:

**Growing MRR**

+

**Shrinking customer base**

+

**Increasing dependence on one customer**

and still appear healthy on a traditional dashboard.

WhaleWatch surfaces that contradiction.

It helps founders, CFOs, finance teams, investors, and operators distinguish between:

> **"Revenue is growing."**

and:

> **"Revenue is growing in a durable and diversified way."**

---

# Future Improvements

Potential extensions include:

- Automated churn-risk forecasting
- Whale churn scenario simulation
- Revenue-at-risk calculations
- Customer survival analysis
- Contract renewal monitoring
- Cohort retention analysis
- Forecasted concentration risk
- Stripe integration
- Salesforce integration
- CRM integrations
- Automated CFO and board reports
- Multi-period customer behavior analysis

---

# Demo

The demo highlights how a strong topline revenue number can hide significant concentration risk.

WhaleWatch surfaces metrics such as:

| Metric | Value |
|---|---:|
| Total MRR | $34.55M |
| Month-over-Month Growth | +20.8% |
| Largest Customer Exposure | 34.7% |
| Gross MRR Loss | $830.2K |

At first glance, **20.8% MRR growth looks excellent**.

But WhaleWatch reveals the more important question:

> **How much of that growth is actually durable?**

By analyzing customer concentration, hidden losses, and whale dependency, WhaleWatch transforms a topline revenue metric into an actionable risk assessment.

---

# The Goal

WhaleWatch transforms:

> **MRR increased 20.8%.**

into:

> **MRR increased 20.8%, but growth is increasingly concentrated. The largest customer now represents 34.7% of total MRR, while the rest of the portfolio experienced approximately $830K in negative movement. Revenue is growing, but the business has become more dependent on a small number of high-value customers.**

---

## 🐋 Don't just track revenue. Track the whales driving it.

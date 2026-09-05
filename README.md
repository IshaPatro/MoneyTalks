# WhaleWatch

> Don't just track revenue. Track the whales driving it.

WhaleWatch is a full-width, dark-themed Streamlit CFO dashboard for SaaS revenue intelligence and customer concentration risk. It streams and aggregates the real 1.15-million-row dataset in `data/output.csv` to expose headline MRR, whale dependency, hidden churn, underlying growth, revenue concentration, and customer momentum. The built-in Concentration Risk Agent explains the real story without requiring an API key.

## Run the app

### 1. Create a virtual environment

**Mac / Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Start WhaleWatch

```bash
streamlit run app.py
```

Open the URL printed in the terminal, normally [http://localhost:8501](http://localhost:8501).

## Project structure

```text
MoneyTalks/
├── app.py              # Streamlit dashboard and local agent
├── assets/logo.png     # WhaleWatch logo
├── data/output.csv     # Full account-month and transaction dataset
├── requirements.txt    # Python dependencies
└── README.md           # Setup and run instructions
```

## Dashboard coverage

- Six CFO KPIs: total MRR, MRR excluding the whale, Top-1 and Top-5 exposure, customer losses, and HHI concentration.
- Four interactive charts: revenue quality, customer concentration, MRR movement bridge, and customer growth map.
- A Concentration Risk Agent that checks the baseline, identifies the largest accounts, spots hidden losses, and explains actual portfolio risk.
- A branded loading screen appears during the first streaming aggregation; subsequent reruns use Streamlit's data cache.
- Green is reserved for positive indicators; red is reserved for losses and risk.
- The analytics workspace uses two-thirds of the screen and the agent uses the remaining one-third.

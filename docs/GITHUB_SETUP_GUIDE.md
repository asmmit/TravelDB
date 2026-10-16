# GitHub Repository Setup Guide for TravelDB

This guide explains which files are uploaded to GitHub, which files are excluded, and how to push this repository to your personal GitHub account.

---

## 1. What Files Are Uploaded vs. Excluded?

| Directory / File | Uploaded? | Reason |
| :--- | :---: | :--- |
| `database/` (SQL schemas, migrations) | ✅ **YES** | Core database design, DDL tables, spatial views, and stored procedures. |
| `network/` (Graph builder, Router, Gas Station Problem) | ✅ **YES** | Core algorithmic engine and Python logic. |
| `pipeline/` (Weather, Traffic, Incident ingestion) | ✅ **YES** | Real-time ingestion pipelines and TomTom/Open-Meteo processors. |
| `web/` (Flask app, templates, css, js) | ✅ **YES** | Frontend dashboard, Leaflet mapping interface, and REST API. |
| `tests/` (Test suite) | ✅ **YES** | Automated unit and integration test verification. |
| `docs/` (Architecture reports, Viva Q&A) | ✅ **YES** | Comprehensive technical documentation and evaluation guides. |
| `requirements.txt` & `README.md` | ✅ **YES** | Enables anyone cloning the repository to reproduce the environment. |
| **`venv/`** | ❌ **NO** | **Never upload virtual environments!** (Contains >15,000 files and >1.5 GB of machine-specific binary executables). Excluded by `.gitignore`. |
| **`__pycache__/` & `*.pyc`** | ❌ **NO** | Compiled Python bytecode. Excluded by `.gitignore`. |
| **`.pytest_cache/`** | ❌ **NO** | Test session cache. Excluded by `.gitignore`. |
| **`.env`** | ❌ **NO** | Contains local MySQL passwords and private API keys. Excluded by `.gitignore`. |

---

## 2. Step-by-Step GitHub Upload Commands

Open your PowerShell terminal in `C:\TravelDB2` and execute the following commands:

### Step 1: Initialize Git and Check Tracked Files
```powershell
# Navigate to project root (if not already there)
cd C:\TravelDB2

# Initialize local git repository
git init

# Stage all project code (respects .gitignore)
git add .

# Check staged files (verify 'venv' is NOT included)
git status
```

### Step 2: Create Your First Commit
```powershell
git commit -m "feat: TravelDB Fuel-Aware Decision Support System (NH 48 Corridor)"
```

### Step 3: Link Your Remote GitHub Repository and Push
1. Go to [github.com](https://github.com) and click **"New repository"**.
2. Name it `TravelDB-South-India` (set to **Public** or **Private** as you prefer).
3. Do **not** initialize with a README (you already have one).
4. Run the following commands in PowerShell (replace `<YOUR_GITHUB_USERNAME>` with your GitHub username):

```powershell
# Rename branch to main
git branch -M main

# Add your GitHub repository as remote origin
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/TravelDB-South-India.git

# Push code to GitHub
git push -u origin main
```

---

## 3. How Other Students or Evaluators Can Run It

Once on GitHub, anyone can clone your repository and set it up with just 3 commands:
```bash
git clone https://github.com/<YOUR_GITHUB_USERNAME>/TravelDB-South-India.git
cd TravelDB-South-India
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python database/migrate.py
python web/app.py
```

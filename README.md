# PackRight Inventory Intelligence

PackRight is a comprehensive inventory intelligence platform designed to eliminate the "Inventory Black Hole" using advanced forecasting, risk scoring, and Machine Learning.

## Features
- **ML Demand Forecasting**: Uses a Random Forest model to predict material demand based on seasonal indices and historical consumption.
- **Risk Intelligence**: Real-time identification of stockout, credit, and supplier risks.
- **Simulation Lab**: Run "What-if" scenarios to see how production changes impact your working capital.
- **Role-Based Alerts**: Automated email alerts for Production, Finance, and Procurement roles.
- **Cloud Ready**: Ready for AWS deployment via Terraform & Ansible.

---

## 🚀 Deployment
- [Local Setup](#quick-setup)
- [Cloud Deployment (AWS)](deployment/DEPLOYMENT.md)

## Quick Setup

### Windows (PowerShell)
Run the automated setup script:
```powershell
.\setup.ps1
```

### Linux / macOS
Run the automated setup script:
```bash
chmod +x setup.sh
./setup.sh
```

---

## Detailed Setup (Manual)

### 1. Create a Virtual Environment (Recommended)
Open your terminal (PowerShell or Command Prompt) and run:
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 2. Install Dependencies
Install all required libraries including pandas, scikit-learn, and joblib:
```powershell
pip install -r requirements.txt
```

### 3. Configuration (.env)
Create a `.env` file in the root directory. You can copy the example:
```powershell
copy .env.example .env
```
Open `.env` and configure your settings:
- `INPUT_DIR`: Directory where CSV data files are stored (default: `data`).
- `OUTPUT_DIR`: Directory where processed results are saved (default: `outputs`).
- `MODEL_DIR`: Directory containing the ML model (default: `models`).
- **SMTP Settings**: If you want to send email alerts, provide your Gmail/SMTP credentials.

### 4. Data and Model Preparation
- Ensure your raw CSV files are in the `data/` folder.
- Ensure the trained ML model (`inventory_forecasting_model.pkl`) is in the `models/` folder.

### 5. Run the Analytics Pipeline
Before starting the server, run the initial computation to generate forecasts and risk scores:
```powershell
python run_pipeline.py
```

### 6. Start the Dashboard
Launch the backend server and web interface:
```powershell
python app.py
```
By default, the application will run at: **http://127.0.0.1:8000**

---

## Usage Guide

### Command Center
The main dashboard provides a bird's-eye view of your operations:
- **Credit Gate**: Monitor working capital utilization.
- **Immediate Actions**: List of materials requiring urgent procurement.
- **Risk Snapshot**: Overview of severity levels across the inventory.

### Simulation Lab
Test different production volumes to see the impact on your credit limit:
1. Navigate to the **Simulation Lab** tab.
2. Adjust the multipliers for different product categories.
3. Click **Run Simulation** to see persistent results and historical comparisons.

### Sending Reports
To send a daily status report via email:
```powershell
python send_daily_report.py --recompute
```

---

## Project Structure
- `app.py`: Main backend server (Python HTTP Server).
- `src/`: Core logic modules (Risk Engine, Forecasting Engine, etc.).
- `web/`: Frontend assets (HTML, CSS, JS).
- `data/`: Input CSV files.
- `models/`: Trained Machine Learning models.
- `outputs/`: Generated analytical reports and logs.

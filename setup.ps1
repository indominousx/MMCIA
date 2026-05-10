# PackRight Setup Script for Windows

Write-Host "Setting up PackRight Inventory Intelligence..." -ForegroundColor Cyan

# 1. Create virtual environment
if (-not (Test-Path "venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv venv
}

# 2. Install dependencies
Write-Host "Installing dependencies from requirements.txt..."
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 3. Initialize environment variables
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env file from example..."
    Copy-Item ".env.example" ".env"
}

# 4. Create necessary directories
if (-not (Test-Path "outputs")) { New-Item -ItemType Directory "outputs" | Out-Null }
if (-not (Test-Path "models")) { New-Item -ItemType Directory "models" | Out-Null }

# 5. Run initial analytics pipeline
Write-Host "Running initial analytics pipeline..." -ForegroundColor Yellow
.\venv\Scripts\python.exe run_pipeline.py

Write-Host "`nSetup Complete!" -ForegroundColor Green
Write-Host "To start the dashboard, run: " -NoNewline
Write-Host ".\venv\Scripts\python.exe app.py" -ForegroundColor Cyan

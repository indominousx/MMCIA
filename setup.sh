#!/bin/bash

# PackRight Setup Script for Linux/macOS

echo "Setting up PackRight Inventory Intelligence..."

# 1. Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# 2. Install dependencies
echo "Installing dependencies from requirements.txt..."
./venv/bin/python3 -m pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

# 3. Initialize environment variables
if [ ! -f ".env" ]; then
    echo "Creating .env file from example..."
    cp .env.example .env
fi

# 4. Create necessary directories
mkdir -p outputs
mkdir -p models

# 5. Run initial analytics pipeline
echo "Running initial analytics pipeline..."
./venv/bin/python3 run_pipeline.py

echo ""
echo "Setup Complete!"
echo "To start the dashboard, run: ./venv/bin/python3 app.py"

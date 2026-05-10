#!/bin/bash
# PackRight Terraform Wrapper for Linux/macOS
# Loads variables from root .env and runs terraform

COMMAND=$1

if [ -z "$COMMAND" ]; then
    echo "Usage: ./terraform_run.sh [command]"
    exit 1
fi

# 1. Load .env variables
if [ -f .env ]; then
    export $(grep '^TF_VAR_' .env | xargs)
    echo "Loaded TF_VAR variables from .env"
else
    echo ".env file not found!"
    exit 1
fi

# 2. Run Terraform in the correct directory
cd deployment/terraform || exit
terraform "$COMMAND"

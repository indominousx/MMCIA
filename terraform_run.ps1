# PackRight Terraform Wrapper for Windows
# This script loads variables from the root .env and passes them to Terraform

param(
    [Parameter(Mandatory=$true)]
    [string]$Command
)

# 1. Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Error "No .env file found in root directory!"
    exit 1
}

# 2. Parse .env for TF_VAR_ variables
$EnvVars = @{}
Get-Content .env | ForEach-Object {
    if ($_ -match "^TF_VAR_([^=]+)=(.*)$") {
        $name = $matches[1]
        $value = $matches[2]
        $EnvVars[$name] = $value
        # Set as process environment variable for Terraform to pick up
        [Environment]::SetEnvironmentVariable("TF_VAR_$name", $value, "Process")
    }
}

Write-Host "Loaded $($EnvVars.Count) variables from .env for Terraform." -ForegroundColor Cyan

# 3. Navigate to terraform directory and run command
$TerraformDir = Join-Path (Get-Location) "deployment/terraform"
if (-not (Test-Path $TerraformDir)) {
    Write-Error "Could not find deployment/terraform directory!"
    exit 1
}

Push-Location $TerraformDir
try {
    Write-Host "Executing: terraform $Command" -ForegroundColor Yellow
    terraform $Command
} finally {
    Pop-Location
}

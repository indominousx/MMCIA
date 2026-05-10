# Cloud Deployment Guide (AWS + Terraform + Ansible)

This guide explains how to deploy the PackRight Inventory Intelligence platform to an AWS EC2 instance.

## Architecture
- **Infrastructure**: AWS EC2 (Ubuntu 22.04) managed by Terraform.
- **Configuration**: Managed by Ansible (Systemd service, Virtualenv, Python 3).

---

## Step 1: Provision Infrastructure (Terraform)

1. Navigate to the terraform directory:
   ```bash
   cd deployment/terraform
   ```
2. Initialize Terraform:
   ```bash
   terraform init
   ```
3. Plan the deployment (you will be prompted for your AWS key name):
   ```bash
   terraform plan -var="key_name=your-aws-key-name"
   ```
4. Apply the changes:
   ```bash
   terraform apply -var="key_name=your-aws-key-name"
   ```
5. Copy the `public_ip` from the output.

---

## Step 2: Configure Server (Ansible)

1. Navigate to the ansible directory:
   ```bash
   cd ../ansible
   ```
2. Edit `inventory.ini` and replace `your_instance_ip` and `path/to/your/key.pem` with your actual values.
3. Run the playbook:
   ```bash
   ansible-playbook -i inventory.ini playbook.yml
   ```

---

## Step 3: SSL Configuration (Optional)

To use your custom domain `mccia.globians.in` with HTTPS:
1. Place your **Origin Certificate** and **Private Key** (e.g., `cert.pem` and `key.pem`) in the root directory of the project.
2. Update your `.env` file with the relative paths:
   ```text
   SSL_CERT_PATH=cert.pem
   SSL_KEY_PATH=key.pem
   ```
3. When you run the Ansible playbook, these files will be automatically securely synchronized to the server.
4. The dashboard will automatically detect these and switch to **HTTPS**.

---

## Step 4: Access the Dashboard

Once the playbook finishes successfully:
1. Open your browser.
2. Navigate to `http://your-instance-ip:8000`.

---

## Step 5: Automated CI/CD (GitHub Actions)

I have included a GitHub Actions workflow in `.github/workflows/main.yml`. To enable automated deployments whenever you push to `main`:

1.  Go to your GitHub Repository -> **Settings** -> **Secrets and variables** -> **Actions**.
2.  Add the following **New repository secrets**:
    *   `SSH_PRIVATE_KEY`: Paste the entire content of your `.pem` key file.
    *   `SERVER_IP`: The Public IP of your EC2 instance (from Terraform output).
3.  Now, every time you `git push origin main`, GitHub will:
    *   Run your Python tests automatically.
    *   If tests pass, it will securely SSH into your AWS server and run the Ansible deployment to update your code.

---

## Maintenance
- **Restarting the service**: `sudo systemctl restart packright`
- **Checking logs**: `sudo journalctl -u packright -f`
- **Updating code**: Re-run the `ansible-playbook` command.

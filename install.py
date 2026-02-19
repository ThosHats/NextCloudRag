#!/usr/bin/env python3
import os
import sys
import subprocess
import time
import json
import socket
import urllib.request
import urllib.error
import ssl
import base64
from getpass import getpass

# ==========================================
# NextCloud RAG Installation Script (Python)
# ==========================================

LOG_FILE = "install_debug.log"

def log(message):
    print(message)
    with open(LOG_FILE, "a") as f:
        f.write(message + "\n")

def run_command(command, check=True, shell=True, capture_output=False):
    """Runs a shell command and logs output."""
    try:
        result = subprocess.run(
            command, 
            check=check, 
            shell=shell, 
            text=True, 
            stdout=subprocess.PIPE if capture_output else None,
            stderr=subprocess.PIPE if capture_output else None
        )
        return result
    except subprocess.CalledProcessError as e:
        log(f"Error executing command: {command}")
        if e.stdout: log(f"Stdout: {e.stdout}")
        if e.stderr: log(f"Stderr: {e.stderr}")
        raise

def error_exit(step, message, container_name=None):
    log("")
    log("==========================================")
    log(f"❌ CRITICAL ERROR IN STEP: {step}")
    log("==========================================")
    log("An error occurred which stopped the installation.")
    log("")
    log("--- DEBUG INFORMATION FOR AI ANALYSIS ---")
    log(f"Failed Command/Message: {message}")
    log("")
    if container_name:
        log(f"--- CONTAINER LOGS ({container_name}) ---")
        try:
            subprocess.run(f"docker logs --tail 100 {container_name}", shell=True)
        except:
            log(f"Could not retrieve logs for {container_name}")
        log("-----------------------------------")
    
    log("--- SYSTEM STATE ---")
    subprocess.run('docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"', shell=True)
    log("")
    log("Please provide this output to your AI assistant.")
    sys.exit(1)

def ensure_package(command_name, package_name):
    if subprocess.call(f"command -v {command_name}", shell=True, stdout=subprocess.DEVNULL) != 0:
        log(f"📦 Package '{command_name}' is missing. Installing...")
        sudo_cmd = "sudo" if subprocess.call("command -v sudo", shell=True, stdout=subprocess.DEVNULL) == 0 else ""
        run_command(f"{sudo_cmd} apt-get update -y")
        run_command(f"{sudo_cmd} apt-get install -y {package_name}")
    else:
        log(f"✅ '{command_name}' is already installed.")

def verify_container_up(container_name):
    log(f"Verifying container '{container_name}' is running...")
    for i in range(5):
        try:
            res = subprocess.run(
                f"docker inspect -f '{{{{.State.Running}}}}' {container_name}", 
                shell=True, capture_output=True, text=True
            )
            if res.stdout.strip() == "true":
                log(f"✅ Container '{container_name}' is UP.")
                time.sleep(1) # Give it a moment
                # Double check
                res = subprocess.run(
                   f"docker inspect -f '{{{{.State.Running}}}}' {container_name}", 
                   shell=True, capture_output=True, text=True
                )
                if res.stdout.strip() == "true":
                     return
        except:
            pass
        time.sleep(1 if i < 4 else 0)
    
    error_exit("VERIFICATION", f"Container {container_name} failed to start/stay up", container_name)

def get_public_ip():
    try:
        with urllib.request.urlopen("https://ifconfig.me") as response:
            return response.read().decode('utf-8').strip()
    except:
        try:
            # Fallback to hostname -I
            res = subprocess.run("hostname -I | awk '{print $1}'", shell=True, capture_output=True, text=True)
            return res.stdout.strip()
        except:
            return "127.0.0.1"

# --- Group Folder Automation Helpers ---

def install_pyyaml():
    try:
        import yaml
    except ImportError:
        log("📦 Installing PyYAML for configuration parsing...")
        run_command(f"{sys.executable} -m pip install pyyaml --break-system-packages", check=False)

def get_group_folder_id(folder_name):
    try:
        res = run_command("docker exec --user www-data nextcloud-aio-nextcloud php occ groupfolders:list --output=json", check=False, capture_output=True)
        if res.returncode == 0:
            import json
            data = json.loads(res.stdout)
            for fid, info in data.items():
                if info['mount_point'] == folder_name:
                    return fid
    except:
        pass
    return None

def process_group_creation():
    if not os.path.exists("config.yaml"): 
        log("ℹ️ No config.yaml, skipping group creation.")
        return
    
    install_pyyaml()
    import yaml
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    log("🔄 Processing groups from config.yaml...")
    for g in config.get('groups', []):
        name = g['name']
        folder = g['folder_name']
        
        # Create Group
        run_command(f"docker exec --user www-data nextcloud-aio-nextcloud php occ group:add {name}", check=False)
        
        # Create Folder
        fid = get_group_folder_id(folder)
        if not fid:
            log(f"   -> Creating group folder: {folder}")
            run_command(f"docker exec --user www-data nextcloud-aio-nextcloud php occ groupfolders:create \"{folder}\"", check=False)
            fid = get_group_folder_id(folder)
        
        if fid:
            # Assign Group
            log(f"   -> Assigning group '{name}' to '{folder}' (Write/Share/Delete)")
            run_command(f"docker exec --user www-data nextcloud-aio-nextcloud php occ groupfolders:group {fid} {name} write share delete", check=False)
            
            # Assign Admin (so we can see it)
            run_command(f"docker exec --user www-data nextcloud-aio-nextcloud php occ groupfolders:group {fid} admin write share delete", check=False)

def assign_bot_to_folders(bot_user):
    if not os.path.exists("config.yaml"): return
    
    import yaml
    with open("config.yaml") as f:
         config = yaml.safe_load(f)
    
    log(f"🔄 granting '{bot_user}' read access to group folders...")     
    for g in config.get('groups', []):
        folder = g['folder_name']
        fid = get_group_folder_id(folder)
        if fid:
            run_command(f"docker exec --user www-data nextcloud-aio-nextcloud php occ groupfolders:group {fid} {bot_user} read", check=False)

# --- Main Execution ---

# Redirect logging
with open(LOG_FILE, "a") as f:
    f.write(f"Starting installation at {time.ctime()}\n")

# Load Configuration from config.yaml
GLOBAL_CONFIG = {}
if os.path.exists("config.yaml"):
    install_pyyaml()
    import yaml
    with open("config.yaml") as f:
        GLOBAL_CONFIG = yaml.safe_load(f)
    log("✅ Loaded configuration from config.yaml")

log("--- Step 1: Checking and Installing Prerequisites ---")

ensure_package("curl", "curl")
ensure_package("openssl", "openssl")
ensure_package("git", "git")

# Docker Check/Install
if subprocess.call("command -v docker", shell=True, stdout=subprocess.DEVNULL) != 0:
    log("🐳 Docker not found. Installing Docker...")
    sudo_cmd = "sudo" if subprocess.call("command -v sudo", shell=True, stdout=subprocess.DEVNULL) == 0 else ""
    run_command(f"{sudo_cmd} apt-get update -y")
    run_command(f"{sudo_cmd} apt-get install -y ca-certificates gnupg lsb-release")
    run_command(f"{sudo_cmd} mkdir -p /etc/apt/keyrings")
    run_command(f"curl -fsSL https://download.docker.com/linux/ubuntu/gpg | {sudo_cmd} gpg --dearmor -o /etc/apt/keyrings/docker.gpg")
    
    # Needs architecture and lsb_release
    dpkg_arch = subprocess.run("dpkg --print-architecture", shell=True, capture_output=True, text=True).stdout.strip()
    lsb_rel = subprocess.run("lsb_release -cs", shell=True, capture_output=True, text=True).stdout.strip()
    
    cmd = f'echo "deb [arch={dpkg_arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu {lsb_rel} stable" | {sudo_cmd} tee /etc/apt/sources.list.d/docker.list > /dev/null'
    run_command(cmd)
    
    run_command(f"{sudo_cmd} apt-get update -y")
    run_command(f"{sudo_cmd} apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin")
else:
    log("✅ Docker is already installed.")

# Ensure Docker is running
sudo_cmd = "sudo" if subprocess.call("command -v sudo", shell=True, stdout=subprocess.DEVNULL) == 0 else ""
if subprocess.call(f"{sudo_cmd} docker info", shell=True, stdout=subprocess.DEVNULL) != 0:
    log("🚀 Starting Docker service...")
    run_command(f"{sudo_cmd} systemctl start docker")
    run_command(f"{sudo_cmd} systemctl enable docker")

if subprocess.call(f"{sudo_cmd} docker info", shell=True, stdout=subprocess.DEVNULL) != 0:
    error_exit("PREREQUISITES", "Docker daemon is not running or accessible even after installation attempt.")

if subprocess.call("docker compose version", shell=True, stdout=subprocess.DEVNULL) != 0:
    error_exit("PREREQUISITES", "Docker Compose (V2) is required but not found.")


log("")
log("--- Step 2: Configuration ---")

public_ip = get_public_ip()
log(f"Detected Public IP: {public_ip}")

base_domain = os.environ.get("BASE_DOMAIN")
if not base_domain:
    default_domain = GLOBAL_CONFIG.get("domain", "example.com")
    prompt = f"Enter Base Domain (default: {default_domain}): "
    base_domain = input(prompt).strip()
    if not base_domain:
        base_domain = default_domain

nextcloud_domain = f"cloud.{base_domain}"
rag_domain = f"rag.{base_domain}"

acme_email = os.environ.get("ACME_EMAIL")
if not acme_email:
    default_email = GLOBAL_CONFIG.get("email", "admin@example.com")
    prompt = f"Enter Email for Let's Encrypt (default: {default_email}): "
    acme_email = input(prompt).strip()
    if not acme_email:
        acme_email = default_email

log("")
log("Configuration:")
log(f"- Base Domain: {base_domain}")
log(f"- Nextcloud:   {nextcloud_domain}")
log(f"- RAG App:     {rag_domain}")
log(f"- Email:       {acme_email}")
log("")

# Network
if subprocess.call("docker network ls | grep -q platform-net", shell=True) != 0:
    try:
        run_command("docker network create platform-net")
    except:
        error_exit("NETWORK", "docker network create platform-net")
log("✅ Network 'platform-net' ready.")


# Step 4: Proxy
log("")
log("--- Step 4: Deploying Reverse Proxy ---")
os.chdir("docker-deploy/proxy")

with open(".env", "w") as f:
    f.write(f"ACME_EMAIL={acme_email}\n")
    f.write(f"NEXTCLOUD_DOMAIN={nextcloud_domain}\n")
    f.write(f"RAG_DOMAIN={rag_domain}\n")
log("Generated proxy/.env")

try:
    run_command("docker compose up -d")
except:
    error_exit("PROXY_DEPLOY", "docker compose up -d (proxy)", "caddy")
verify_container_up("caddy")
os.chdir("../..")


# Step 5: Nextcloud AIO
log("")
log("--- Step 5: Deploying Nextcloud AIO ---")
os.chdir("docker-deploy/nextcloud-aio")

with open(".env", "w") as f:
    f.write(f"NEXTCLOUD_DOMAIN={nextcloud_domain}\n")
log("Generated nextcloud-aio/.env")

try:
    run_command("docker compose up -d")
except:
    error_exit("NEXTCLOUD_DEPLOY", "docker compose up -d (nextcloud)", "nextcloud-aio-mastercontainer")
verify_container_up("nextcloud-aio-mastercontainer")

log("")
log("----------------------------------------------------------------")
log("ATTENTION: Nextcloud AIO Setup Needed")
log("----------------------------------------------------------------")
log("Open the following URL in your browser to complete the Nextcloud setup:")
log(f"https://{public_ip}:8080")
log("")
log("Important:")
log("1. Your browser will show a 'Connection not private' warning.")
log("2. Click 'Advanced' and then 'Proceed' (this is safe for the setup).")
log("3. Follow the instructions on the page.")
log(f"4. Use the Domain: {nextcloud_domain}")
log("5. After finishing the setup and starting the containers,")
log(f"   Nextcloud will be available at: https://{nextcloud_domain}")
log("----------------------------------------------------------------")
log("")
input("Press [Enter] once you have finished the Nextcloud AIO setup...")

# Auto enable webhook listeners
log("Activating Webhook Listeners app in Nextcloud...")
try:
    run_command("docker exec -u www-data nextcloud-aio-nextcloud php occ app:enable webhook_listeners")
except:
    log("⚠️ Warning: Could not enable app automatically. Please enable 'Webhook Listeners' manually in the Nextcloud App Store.")

# Enable allow_local_remote_servers to ensure webhooks to local/public domains work
log("Configuring Nextcloud to allow local remote servers (required for Webhooks)...")
try:
    run_command("docker exec --user www-data nextcloud-aio-nextcloud php occ config:system:set allow_local_remote_servers --value=true --type=bool", check=False)
    log("   -> 'allow_local_remote_servers' enabled.")
    
    # Enable Group Folders app
    log("   -> Enabling 'groupfolders' app...")
    run_command("docker exec --user www-data nextcloud-aio-nextcloud php occ app:enable groupfolders", check=False)
    log("   -> 'groupfolders' enabled.")
    
    # Process Group Folders from Config
    process_group_creation()
    
except Exception as e:
    log(f"⚠️ Warning: Could not set allow_local_remote_servers or enable 'groupfolders': {e}")

os.chdir("../..")


# Step 6: RAG Stack Config
log("")
log("--- Step 6: Preparing RAG Stack ---")
os.chdir("docker-deploy/rag-stack")

log("Generating secure database passwords...")
postgres_password = subprocess.run("openssl rand -hex 20", shell=True, capture_output=True, text=True).stdout.strip()
if not postgres_password:
    # Python fallback if openssl fails
    import secrets
    postgres_password = secrets.token_hex(20)
log("✅ Database passwords generated.")


# Webhook Automation
log("")
log("----------------------------------------------------------------")
log("SETUP: Nextcloud Webhook Automation")
log("----------------------------------------------------------------")
log("We will now automatically register the necessary webhooks via the Nextcloud API.")
log("Please provide your Nextcloud Admin credentials to authorize this action.")
log("")

nc_admin_user = input("Enter Nextcloud Admin Username (default: admin): ").strip()
if not nc_admin_user: nc_admin_user = "admin"
nc_admin_pass = getpass("Enter Nextcloud Admin Password: ")
print("") 

rag_webhook_url = f"https://{rag_domain}/webhook/nextcloud"
log(f"Target Webhook URL: {rag_webhook_url}")
log("")

nextcloud_url = f"https://{nextcloud_domain}"

def register_webhook(endpoint, event, user, password, base_url):
    url = f"{base_url}/ocs/v2.php/apps/webhook_listeners/api/v1/webhooks"
    print(f"   -> Registering event: {event}...")
    
    payload = {
        "uri": endpoint,
        "event": event,
        "httpMethod": "POST",
        "authMethod": "header",
        "authData": {"X-Nextcloud-Token": "insecure-placeholder-for-now"}
    }
    
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, method='POST')
    req.add_header('OCS-APIRequest', 'true')
    req.add_header('Content-Type', 'application/json')
    
    auth_str = f"{user}:{password}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    req.add_header('Authorization', f'Basic {encoded_auth}')
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    try:
        with urllib.request.urlopen(req, context=ctx) as response:
            if response.status in [200, 201]:
                 print("      ✅ Success.")
            else:
                 print(f"      ❌ Failed with status: {response.status}")
    except urllib.error.HTTPError as e:
        error_content = e.read().decode('utf-8')
        print(f"      ❌ Failed (HTTP {e.code}).")
        print(f"      Payload Sent: {json.dumps(payload)}")
        print(f"      Response: {error_content if error_content else '[Empty Response]'}")
    except Exception as e:
        print(f"      ❌ Critical Error: {str(e)}")

register_webhook(rag_webhook_url, "OCP\\Files\\Events\\Node\\NodeCreatedEvent", nc_admin_user, nc_admin_pass, nextcloud_url)
register_webhook(rag_webhook_url, "OCP\\Files\\Events\\Node\\NodeWrittenEvent", nc_admin_user, nc_admin_pass, nextcloud_url)
register_webhook(rag_webhook_url, "OCP\\Files\\Events\\Node\\NodeDeletedEvent", nc_admin_user, nc_admin_pass, nextcloud_url)


# Verify Webhooks
log("")
log("Verifying registered webhooks...")
try:
    verify_url = f"{nextcloud_url}/ocs/v2.php/apps/webhook_listeners/api/v1/webhooks"
    req = urllib.request.Request(verify_url, method='GET')
    req.add_header('OCS-APIRequest', 'true')
    req.add_header('Content-Type', 'application/json')
    
    auth_str = f"{nc_admin_user}:{nc_admin_pass}"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    req.add_header('Authorization', f'Basic {encoded_auth}')
    
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    
    with urllib.request.urlopen(req, context=ctx) as response:
        body = response.read().decode('utf-8')
        if rag_webhook_url in body:
             log("✅ Verification Successful: Webhooks are active.")
        else:
             log("⚠️  Verification Failed: Could not find the registered URL in the list.")
             log(f"Debug Response: {body}")
except Exception as e:
     log(f"⚠️  Verification checks failed with error: {e}")


nextcloud_webhook_secret = subprocess.run("openssl rand -hex 20", shell=True, capture_output=True, text=True).stdout.strip()
if not nextcloud_webhook_secret:
    import secrets
    nextcloud_webhook_secret = secrets.token_hex(20)

log("")
log(f"generated internal webhook secret: {nextcloud_webhook_secret}")


# WebDAV / Bot User
log("")
log("")
log("----------------------------------------------------------------")
log("SETUP: WebDAV / Bot User (Automated)")
log("----------------------------------------------------------------")
log("Checking for 'rag-bot' user...")

webdav_password = ""
import secrets

# Check if user exists
res = run_command("docker exec --user www-data nextcloud-aio-nextcloud php occ user:info rag-bot", check=False, capture_output=True)
if res.returncode != 0:
    # Create user
    log("   -> 'rag-bot' not found. Creating automatically...")
    gen_pass = secrets.token_urlsafe(20)
    
    # We pass the password via env variable into the container command
    cmd = f"docker exec --user www-data -e OC_PASS='{gen_pass}' nextcloud-aio-nextcloud php occ user:add --password-from-env --display-name='RAG Bot' rag-bot"
    
    # Run creation
    c_res = run_command(cmd, check=False)
    
    if c_res.returncode == 0:
        log(f"✅ Created user 'rag-bot' successfully.")
        webdav_password = gen_pass
    else:
        log("❌ Failed to create 'rag-bot' automatically.")
else:
    log("ℹ️ User 'rag-bot' already exists.")
    webdav_password = input("   Enter the existing password for 'rag-bot': ").strip()

# Grant Access to Group Folders
assign_bot_to_folders("rag-bot")

if not webdav_password:
    log("⚠️ Could not generate or retrieve password automatically.")
    webdav_password = input("Enter the Nextcloud Password for 'rag-bot' manually: ").strip()


# OpenAI Configuration
log("")
log("----------------------------------------------------------------")
log("SETUP: AI Model (OpenAI)")
log("----------------------------------------------------------------")
log("The system uses OpenAI for processing text and answering questions.")
log("1. Go to https://platform.openai.com/")
log("2. Login and navigate to 'API Keys'.")
log("3. Create a new secret key.")
log("")
openai_api_key = input("Enter your OpenAI API Key (sk-...): ").strip()


# OIDC Authentication
log("")
log("----------------------------------------------------------------")
log("SETUP: Authentication (OIDC)")
log("----------------------------------------------------------------")
log("Do you want to use OpenID Connect (OIDC) for user authentication?")
log("This is required if you want to restrict the web UI to specific users.")
use_oidc = input("Use OIDC? (y/n): ").strip().lower()

oidc_issuer = "none"
oidc_client_id = "none"
oidc_audience = "none"

if use_oidc.startswith("y"):
    log("")
    log("Please provide your OIDC details (from Keycloak, Authentik, etc.):")
    oidc_issuer = input("OIDC Issuer URL: ").strip()
    oidc_client_id = input("OIDC Client ID: ").strip()
    oidc_audience = input("OIDC Audience: ").strip()

# Generate .env
env_content = f"""# Domain Configuration
RAG_DOMAIN={rag_domain}

# Nextcloud Connection
NEXTCLOUD_URL=https://{nextcloud_domain}
NEXTCLOUD_WEBHOOK_SECRET={nextcloud_webhook_secret}

# WebDAV Bot Configuration
WEBDAV_USER=rag-bot
WEBDAV_PASSWORD={webdav_password}

# Databases
POSTGRES_USER=rag_user
POSTGRES_PASSWORD={postgres_password}
POSTGRES_DB=rag_metadata

# Authentication (OIDC)
OIDC_ISSUER={oidc_issuer}
OIDC_CLIENT_ID={oidc_client_id}
OIDC_AUDIENCE={oidc_audience}

# LLM Provider
OPENAI_API_KEY={openai_api_key}
"""

with open(".env", "w") as f:
    f.write(env_content)

log("")
log("✅ Generated rag-stack/.env with your provided configuration.")
log("----------------------------------------------------------------")
log("")
input("Press [Enter] to start the deployment of the RAG stack...")


# Step 7: RAG Deployment
log("")
log("--- Step 7: Deploying RAG Stack ---")
try:
    run_command("docker compose build")
except:
    error_exit("RAG_BUILD", "docker compose build")

try:
    run_command("docker compose up -d")
except:
    error_exit("RAG_DEPLOY", "docker compose up -d")

verify_container_up("rag-indexer-worker")
verify_container_up("rag-haystack-api")

log("")
log("==========================================")
log("✅ INSTALLATION SUCCESSFUL")
log("==========================================")

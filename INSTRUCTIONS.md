# Installation Instructions

## Overview
This system is composed of three Docker stacks:
1.  **Proxy:** Caddy (handles HTTPS/Routing).
2.  **Nextcloud:** The standard AIO implementation.
3.  **RAG Stack:** Our custom AI services.

The installation is automated via `./install.sh`.

---

## 🚀 Quick Start

1.  **Run the script:**
    ```bash
    ./install.sh
    ```
2.  **Follow the prompts:**
    - Enter your **Base Domain** (e.g., `example.com`).
      - The system will create `cloud.example.com` (Nextcloud) and `rag.example.com` (RAG API).
    - Enter your email for SSL.

The script will set up the network, proxy, and Nextcloud. It will then **pause** and ask you to enter sensitive credentials.

---

## 🔐 Credentials Explanation (Manual Step)

When the script pauses at **Step 6**, you must edit `docker-deploy/rag-stack/.env`. Here is why and how:

### 1. WEBDAV_PASSWORD
*   **What is it?** A specific password for the bot user (`readonly-bot`) to access files via WebDAV without full login.
*   **Why manual?** This cannot be automated securely. It must be generated inside your specific Nextcloud instance after it is installed.
*   **How to get it:**
    1.  Go to `https://<YOUR_SERVER_IP>:8080` (AIO Setup Interface) and finish the setup. Then log in as Admin.
    2.  Create a user named `readonly-bot`.
    3.  Log in as `readonly-bot` (or use "Impersonate").
    4.  Go to **Settings** -> **Security**.
    5.  Scroll to **Devices & sessions**.
    6.  Create a new App Password named "RAG System".
    7.  Copy the token and paste it into `.env`.

### 2. OPENAI_API_KEY
*   **What is it?** Your private key to access OpenAI's models (GPT-4).
*   **Why manual?** This is your private billing key.
*   **How to get it:** Get it from [platform.openai.com](https://platform.openai.com/api-keys) and paste it into `.env`.

### 3. OIDC Secrets (Optional/Advanced)
*   **What is it?** Configuration for Single Sign-On (SSO).
*   **Why manual?** Depends entirely on your Identity Provider (Keycloak, Authentik, etc.).
*   **Requirement:** If you want secure Chat Access, configure `OIDC_ISSUER` and `OIDC_CLIENT_ID`. If left empty/mocked, the system runs in unsecured/dev mode.

---

## Verification

After you save the `.env` file and press Enter in the script, it will deploy the RAG services.
You should see:
```
✅ Container 'rag-indexer-worker' is UP.
✅ Container 'rag-haystack-api' is UP.
✅ INSTALLATION SUCCESSFUL
```

If a container fails (e.g., "Restarting"), checking the logs `docker logs rag-indexer-worker` usually reveals that a password variable is missing or invalid.

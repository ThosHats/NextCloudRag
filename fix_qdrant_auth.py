
import os
import secrets

ENV_FILE = "docker-deploy/rag-stack/.env"

def fix_env():
    if not os.path.exists(ENV_FILE):
        print(f"❌ {ENV_FILE} not found.")
        return

    with open(ENV_FILE, "r") as f:
        content = f.read()

    if "QDRANT_API_KEY=" in content:
        print("✅ QDRANT_API_KEY already exists in .env.")
        # We might want to ensure it's not empty?
        # But let's assume if it exists, the user set it or previous logic did.
        # Check if it has a value
        for line in content.splitlines():
            if line.startswith("QDRANT_API_KEY=") and len(line.strip()) > 15:
                print("   -> And it seems to have a value.")
                return

    # Generate Key
    new_key = secrets.token_urlsafe(32)
    print(f"🔑 Generated new Qdrant API Key: {new_key[:5]}...")

    # Append or Replace
    if "QDRANT_API_KEY=" in content:
        # It exists but is empty/short, let's replace (simple replace might be risky if multiline, but usually safe for .env)
        # Actually, simpler to just append if not there, or notify user. 
        # But since we want to automate:
        lines = content.splitlines()
        new_lines = []
        replaced = False
        for line in lines:
            if line.startswith("QDRANT_API_KEY="):
                new_lines.append(f"QDRANT_API_KEY={new_key}")
                replaced = True
            else:
                new_lines.append(line)
        if not replaced: new_lines.append(f"QDRANT_API_KEY={new_key}") # Should not happen if check passed
        
        with open(ENV_FILE, "w") as f:
            f.write("\n".join(new_lines) + "\n")
    else:
        # Append
        with open(ENV_FILE, "a") as f:
            f.write(f"\nQDRANT_API_KEY={new_key}\n")

    print("✅ Updated .env file.")

if __name__ == "__main__":
    fix_env()

import os
import hashlib
import requests
import json

# Setting this to True will lock down the application and require a valid license key to run.
# If False, the application runs in "Community Edition" free mode.
REQUIRE_LICENSE = False

# Local mock key validation hash for offline testing: 
# SHA256 of "AI-STUDIO-PRO-DEV-KEY" is "d37e6f85ff537ad108f9df0b892a06141a02195f1d43235b2e6398fb9a88eb05"
_DEVELOPER_KEY_HASH = "d37e6f85ff537ad108f9df0b892a06141a02195f1d43235b2e6398fb9a88eb05"

class LicenseService:
    def __init__(self, settings_manager=None):
        self.settings = settings_manager
        
    def get_license_key(self) -> str:
        if self.settings and hasattr(self.settings, "get"):
            return self.settings.get("license_key", "")
        return os.environ.get("AI_STUDIO_LICENSE_KEY", "")
        
    def save_license_key(self, key: str):
        if self.settings and hasattr(self.settings, "set"):
            self.settings.set("license_key", key)
            
    def validate_license(self, key: str = None) -> tuple[bool, str, dict]:
        """
        Validate the license key.
        Returns (is_valid, message, details_dict).
        """
        if not REQUIRE_LICENSE and not key:
            return True, "Running in Free Community Edition", {"tier": "Community", "status": "active"}
            
        target_key = key or self.get_license_key()
        target_key = target_key.strip()
        
        if not target_key:
            if REQUIRE_LICENSE:
                return False, "License key is required to use this application.", {}
            return True, "Running in Free Community Edition", {"tier": "Community", "status": "active"}
            
        # 1. Local Cryptographic Offline Check (Developer/Offline Keys)
        key_hash = hashlib.sha256(target_key.encode("utf-8")).hexdigest()
        if key_hash == _DEVELOPER_KEY_HASH:
            return True, "Offline Developer License Activated", {"tier": "Developer", "status": "active", "expires": "Never"}
            
        # 2. Remote Validation Hook
        # Later, replace this with your licensing server URL (e.g. Gumroad, Lemon Squeezy, or custom API)
        license_server_url = os.environ.get("AI_STUDIO_LICENSING_SERVER", "")
        if license_server_url:
            try:
                response = requests.post(
                    license_server_url,
                    json={"license_key": target_key},
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("valid"):
                        return True, "License key validated successfully.", data.get("details", {})
                    return False, data.get("message", "Invalid license key."), {}
            except Exception as e:
                # If server is offline, fall back to warning or allow grace period
                return False, f"Licensing server offline. Could not validate: {e}", {}
                
        # Fallback if no server is configured but a key is entered
        # Let's support a simple structural check for a key pattern like "STUDIO-PRO-XXXX"
        if target_key.startswith("STUDIO-PRO-") and len(target_key) >= 16:
            return True, "Standard Pro License Key Activated", {"tier": "Pro", "status": "active"}
            
        return False, "Invalid license key format.", {}

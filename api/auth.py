"""
API Authentication Module

Handles API key validation, generation, and user session tracking.
All authentication logic is kept server-side for security.
"""

import hashlib
import secrets
import time
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class APIKeyData:
    """Data associated with an API key."""
    key_hash: str
    created_at: float
    last_used: float
    requests_count: int = 0
    is_active: bool = True
    tier: str = "free"  # free, pro, enterprise
    rate_limit: int = 60  # requests per minute
    features: list[str] = field(default_factory=lambda: ["transcribe", "notes"])


# In-memory store (replace with database in production)
_api_keys: dict[str, APIKeyData] = {}

# Default demo key for testing
_DEMO_KEY = "ai-noter-demo-key-2024"
_api_keys[hashlib.sha256(_DEMO_KEY.encode()).hexdigest()] = APIKeyData(
    key_hash=hashlib.sha256(_DEMO_KEY.encode()).hexdigest(),
    created_at=time.time(),
    last_used=time.time(),
    tier="demo",
    rate_limit=30,
    features=["transcribe", "notes"],
)


def generate_api_key(prefix: str = "aimn") -> str:
    """
    Generate a new API key.
    
    Args:
        prefix: Prefix for the API key (helps identify key type).
        
    Returns:
        New API key string.
    """
    random_part = secrets.token_urlsafe(24)
    api_key = f"{prefix}_{random_part}"
    
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    _api_keys[key_hash] = APIKeyData(
        key_hash=key_hash,
        created_at=time.time(),
        last_used=time.time(),
    )
    
    return api_key


def validate_api_key(api_key: str) -> Optional[APIKeyData]:
    """
    Validate an API key and return its associated data.
    
    Args:
        api_key: The API key to validate.
        
    Returns:
        APIKeyData if valid, None otherwise.
    """
    if not api_key:
        return None
    
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_data = _api_keys.get(key_hash)
    
    if key_data and key_data.is_active:
        key_data.last_used = time.time()
        key_data.requests_count += 1
        return key_data
    
    return None


def has_feature(api_key: str, feature: str) -> bool:
    """
    Check if an API key has access to a specific feature.
    
    Args:
        api_key: The API key to check.
        feature: Feature name to check access for.
        
    Returns:
        True if the key has access to the feature.
    """
    key_data = validate_api_key(api_key)
    if not key_data:
        return False
    return feature in key_data.features


def get_rate_limit(api_key: str) -> int:
    """
    Get the rate limit for an API key.
    
    Args:
        api_key: The API key.
        
    Returns:
        Rate limit (requests per minute).
    """
    key_data = validate_api_key(api_key)
    if not key_data:
        return 0
    return key_data.rate_limit


def revoke_api_key(api_key: str) -> bool:
    """
    Revoke an API key.
    
    Args:
        api_key: The API key to revoke.
        
    Returns:
        True if key was found and revoked.
    """
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    key_data = _api_keys.get(key_hash)
    
    if key_data:
        key_data.is_active = False
        return True
    return False

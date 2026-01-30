"""
API Security Middleware

Rate limiting, authentication, and request logging middleware.
All security checks happen server-side.
"""

import time
import logging
from collections import defaultdict
from typing import Callable
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .auth import validate_api_key

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Token bucket rate limiting middleware.
    
    Limits requests per API key to prevent abuse.
    """
    
    def __init__(self, app, default_limit: int = 60, window_seconds: int = 60):
        super().__init__(app)
        self.default_limit = default_limit
        self.window_seconds = window_seconds
        # Track requests: {key_hash: [(timestamp, count), ...]}
        self._requests: dict[str, list[float]] = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next: Callable):
        # Skip rate limiting for non-API routes
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        
        # Get API key from header
        api_key = request.headers.get("X-API-Key", "")
        
        if not api_key:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Missing API key", "code": "MISSING_API_KEY"}
            )
        
        # Validate and get key data
        key_data = validate_api_key(api_key)
        if not key_data:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Invalid API key", "code": "INVALID_API_KEY"}
            )
        
        # Check rate limit
        now = time.time()
        key_hash = key_data.key_hash
        rate_limit = key_data.rate_limit
        
        # Clean old entries
        self._requests[key_hash] = [
            ts for ts in self._requests[key_hash] 
            if now - ts < self.window_seconds
        ]
        
        if len(self._requests[key_hash]) >= rate_limit:
            retry_after = self.window_seconds - (now - self._requests[key_hash][0])
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Rate limit exceeded",
                    "code": "RATE_LIMIT_EXCEEDED",
                    "retry_after": int(retry_after),
                },
                headers={"Retry-After": str(int(retry_after))}
            )
        
        # Record this request
        self._requests[key_hash].append(now)
        
        # Store key data in request state for route handlers
        request.state.api_key_data = key_data
        
        # Add rate limit headers to response
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(rate_limit)
        response.headers["X-RateLimit-Remaining"] = str(
            rate_limit - len(self._requests[key_hash])
        )
        response.headers["X-RateLimit-Reset"] = str(
            int(now + self.window_seconds)
        )
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs all API requests for monitoring and debugging.
    """
    
    async def dispatch(self, request: Request, call_next: Callable):
        start_time = time.time()
        
        # Log request
        logger.info(
            f"Request: {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'}"
        )
        
        response = await call_next(request)
        
        # Log response
        duration = time.time() - start_time
        logger.info(
            f"Response: {response.status_code} "
            f"Duration: {duration:.3f}s"
        )
        
        return response


def require_feature(feature: str):
    """
    Dependency that checks if the API key has access to a feature.
    
    Usage:
        @app.post("/api/v1/transcribe")
        async def transcribe(request: Request, _=Depends(require_feature("transcribe"))):
            ...
    """
    async def check_feature(request: Request):
        key_data = getattr(request.state, "api_key_data", None)
        if not key_data:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required"
            )
        
        if feature not in key_data.features:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{feature}' not available for your plan"
            )
        
        return True
    
    return check_feature

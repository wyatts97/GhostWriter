"""Ghost Admin API client for creating and managing blog posts.

Caches JWTs until they are 50% expired to reduce unnecessary signing overhead.
"""

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import httpx
from structlog import get_logger

logger = get_logger(__name__)


class GhostAuthError(Exception):
    """Raised when Ghost Admin API authentication fails."""


class GhostApiError(Exception):
    """Raised for Ghost API errors."""


class GhostClient:
    """Client for the Ghost Admin API with JWT caching."""

    def __init__(self, admin_url: str = "", admin_api_key: str = ""):
        self.admin_url = admin_url.rstrip("/")
        self.admin_api_key = admin_api_key
        self._api_key_id: str | None = None
        self._api_key_secret: str | None = None
        self._parse_api_key()

        # JWT cache
        self._cached_jwt: str | None = None
        self._jwt_issued_at: float = 0.0
        self._jwt_lifetime: float = 300.0  # 5 minutes

    def _parse_api_key(self) -> None:
        """Parse the Ghost Admin API Key into its id and secret components."""
        if not self.admin_api_key or ":" not in self.admin_api_key:
            self._api_key_id = None
            self._api_key_secret = None
            return
        parts = self.admin_api_key.split(":", 1)
        self._api_key_id = parts[0]
        self._api_key_secret = parts[1]

    def _get_jwt(self) -> str:
        """Return a valid JWT, generating a new one only if the cached token is >50% expired."""
        if self._cached_jwt and (time.time() - self._jwt_issued_at) < (self._jwt_lifetime * 0.5):
            return self._cached_jwt
        self._cached_jwt = self._generate_jwt()
        self._jwt_issued_at = time.time()
        return self._cached_jwt

    def _generate_jwt(self) -> str:
        """Generate a short-lived JWT for Ghost Admin API authentication."""
        if not self._api_key_id or not self._api_key_secret:
            raise GhostAuthError("Admin API Key is not properly configured")

        header = {
            "alg": "HS256",
            "typ": "JWT",
            "kid": self._api_key_id,
        }

        now = int(time.time())
        payload = {
            "exp": now + int(self._jwt_lifetime),
            "iat": now,
            "aud": "/admin/",
        }

        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())

        signing_input = f"{header_b64}.{payload_b64}"
        signature = hmac.new(
            self._api_key_secret.encode("utf-8"),
            signing_input.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_b64 = self._base64url_encode(signature)

        return f"{signing_input}.{signature_b64}"

    @staticmethod
    def _base64url_encode(data: bytes) -> str:
        """Base64 URL-safe encoding without padding."""
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    def _get_headers(self) -> dict[str, str]:
        """Generate auth headers for Ghost Admin API requests using cached JWT."""
        token = self._get_jwt()
        return {
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
            "Accept-Version": "v5.0",
        }

    async def test_connection(self) -> bool:
        """Test the Ghost Admin API connection by fetching the site settings."""
        if not self.admin_url or not self.admin_api_key:
            return False

        try:
            url = f"{self.admin_url}/ghost/api/admin/site/"
            headers = self._get_headers()

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                logger.info("ghost_connection_success")
                return True

            logger.warning(
                "ghost_connection_failed",
                status_code=response.status_code,
                response=response.text[:200],
            )
            return False

        except Exception as exc:
            logger.error("ghost_connection_error", error=str(exc))
            return False

    async def create_post(
        self,
        *,
        title: str,
        content_html: str,
        status: str = "draft",
        excerpt: str | None = None,
        feature_image: str | None = None,
        feature_image_alt: str | None = None,
        tags: list[str] | None = None,
        meta_title: str | None = None,
        meta_description: str | None = None,
        og_image: str | None = None,
        og_title: str | None = None,
        og_description: str | None = None,
        twitter_image: str | None = None,
        twitter_title: str | None = None,
        twitter_description: str | None = None,
    ) -> dict[str, Any]:
        """Create a new post in Ghost via the Admin API."""
        url = f"{self.admin_url}/ghost/api/admin/posts/"
        headers = self._get_headers()

        post: dict[str, Any] = {
            "title": title,
            "html": content_html,
            "status": status,
            "visibility": "public",
        }

        if excerpt:
            post["custom_excerpt"] = excerpt
        if feature_image:
            post["feature_image"] = feature_image
        if feature_image_alt:
            post["feature_image_alt"] = feature_image_alt
        if tags:
            post["tags"] = [{"name": t} for t in tags]

        if meta_title:
            post["meta_title"] = meta_title
        if meta_description:
            post["meta_description"] = meta_description
        if og_image:
            post["og_image"] = og_image
        if og_title:
            post["og_title"] = og_title
        if og_description:
            post["og_description"] = og_description
        if twitter_image:
            post["twitter_image"] = twitter_image
        if twitter_title:
            post["twitter_title"] = twitter_title
        if twitter_description:
            post["twitter_description"] = twitter_description

        body = {"posts": [post]}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=body, headers=headers)

        if response.status_code not in (200, 201):
            logger.error(
                "ghost_create_post_failed",
                status_code=response.status_code,
                response=response.text[:500],
            )
            raise GhostApiError(
                f"Ghost API returned {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        created = data.get("posts", [{}])[0]
        logger.info(
            "ghost_post_created",
            post_id=created.get("id"),
            status=status,
        )
        return created

"""Ghost Admin API client for creating and managing blog posts."""

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
    """Client for the Ghost Admin API.

    Handles JWT-based authentication and provides methods
    for creating posts with full SEO metadata.
    """

    def __init__(self, admin_url: str = "", admin_api_key: str = ""):
        self.admin_url = admin_url.rstrip("/")
        self.admin_api_key = admin_api_key
        self._api_key_id: str | None = None
        self._api_key_secret: str | None = None
        self._parse_api_key()

    def _parse_api_key(self) -> None:
        """Parse the Ghost Admin API Key into its id and secret components."""
        if not self.admin_api_key or ":" not in self.admin_api_key:
            self._api_key_id = None
            self._api_key_secret = None
            return
        parts = self.admin_api_key.split(":", 1)
        self._api_key_id = parts[0]
        self._api_key_secret = parts[1]

    def _generate_jwt(self) -> str:
        """Generate a short-lived JWT for Ghost Admin API authentication.

        The JWT is signed with the Admin API Key secret and includes
        the key ID in the header for Ghost to identify which key is being used.
        """
        if not self._api_key_id or not self._api_key_secret:
            raise GhostAuthError("Admin API Key is not properly configured")

        # Header
        header = {
            "alg": "HS256",
            "typ": "JWT",
            "kid": self._api_key_id,
        }

        # Payload - 5 minute expiry
        now = int(time.time())
        payload = {
            "exp": now + 300,  # 5 minutes
            "iat": now,
            "aud": "/admin/",
        }

        # Encode
        header_b64 = self._base64url_encode(json.dumps(header).encode())
        payload_b64 = self._base64url_encode(json.dumps(payload).encode())

        # Sign
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
        """Generate auth headers for Ghost Admin API requests."""
        token = self._generate_jwt()
        return {
            "Authorization": f"Ghost {token}",
            "Content-Type": "application/json",
            "Accept-Version": "v5.0",
        }

    async def test_connection(self) -> bool:
        """Test the Ghost Admin API connection by fetching the site settings.

        Returns True if the connection is valid, False otherwise.
        """
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
        """Create a new post in Ghost via the Admin API.

        Args:
            title: Post title
            content_html: Post body as HTML
            status: "draft" or "published"
            excerpt: Custom excerpt for the post
            feature_image: URL for the feature image
            feature_image_alt: Alt text for the feature image
            tags: List of tag names
            meta_title: SEO meta title
            meta_description: SEO meta description
            og_image: Open Graph image URL
            og_title: Open Graph title
            og_description: Open Graph description
            twitter_image: Twitter card image URL
            twitter_title: Twitter card title
            twitter_description: Twitter card description

        Returns:
            The created post data from Ghost API.
        """
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

        # SEO fields
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

        payload: dict[str, Any] = {"posts": [post]}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("ghost_post_timeout", title=title)
            raise GhostApiError("Ghost API request timed out") from exc
        except httpx.RequestError as exc:
            logger.error("ghost_post_connection_error", title=title, error=str(exc))
            raise GhostApiError(f"Ghost API connection error: {exc}") from exc

        if response.status_code in (200, 201):
            data = response.json()
            created_post = data.get("posts", [{}])[0]
            logger.info(
                "ghost_post_created",
                post_id=created_post.get("id"),
                title=title,
                status=status,
            )
            return created_post

        if response.status_code == 401:
            raise GhostAuthError(
                f"Ghost API authentication failed: {response.text}"
            )
        if response.status_code == 422:
            raise GhostApiError(
                f"Ghost API validation error: {response.text}"
            )
        if response.status_code == 429:
            raise GhostApiError(
                f"Ghost API rate limited: {response.text}"
            )

        raise GhostApiError(
            f"Ghost API error ({response.status_code}): {response.text}"
        )

    async def get_post(self, post_id: str) -> dict[str, Any]:
        """Fetch a single post by ID."""
        url = f"{self.admin_url}/ghost/api/admin/posts/{post_id}/"
        headers = self._get_headers()

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 200:
                data = response.json()
                return data.get("posts", [{}])[0]

            raise GhostApiError(
                f"Failed to fetch post ({response.status_code}): {response.text}"
            )

        except httpx.RequestError as exc:
            raise GhostApiError(f"Ghost API connection error: {exc}") from exc

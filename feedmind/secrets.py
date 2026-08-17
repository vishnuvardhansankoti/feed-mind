"""
secrets.py — Load secrets from GCP Secret Manager at function startup.
"""

import logging

from google.cloud import secretmanager

from feedmind import config

logger = logging.getLogger(__name__)


def _load_secret(client: secretmanager.SecretManagerServiceClient, name: str) -> str:
    """Fetch the latest version of a secret from Secret Manager."""
    secret_path = f"projects/{config.GCP_PROJECT_ID}/secrets/{name}/versions/latest"
    response = client.access_secret_version(request={"name": secret_path})
    return response.payload.data.decode("utf-8").strip()


def load_all_secrets() -> dict:
    """
    Load all required secrets from GCP Secret Manager.

    Returns:
        dict with keys: telegram_token, telegram_chat_id, gemini_api_key

    Raises:
        RuntimeError if any secret cannot be loaded.
    """
    client = secretmanager.SecretManagerServiceClient()

    required = {
        "telegram_token": config.SECRET_NAME_TELEGRAM_TOKEN,
        "telegram_chat_id": config.SECRET_NAME_TELEGRAM_CHAT_ID,
        "gemini_api_key": config.SECRET_NAME_GEMINI_API_KEY,
    }

    secrets = {}
    for key, secret_name in required.items():
        try:
            secrets[key] = _load_secret(client, secret_name)
            logger.info("Secret loaded: %s", secret_name)
        except Exception as exc:
            raise RuntimeError(f"Failed to load secret '{secret_name}': {exc}") from exc

    return secrets

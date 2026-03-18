from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import boto3
import structlog
from botocore.exceptions import ClientError

from hopefx.config.settings import settings

logger = structlog.get_logger()


class CloudSecretsManager:
    """Cloud-native secrets management with multi-provider support."""

    def __init__(self) -> None:
        self.provider = settings.secrets_provider
        self._client: Any = None
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl = 300
        self._lock = asyncio.Lock()

    async def get_secret(self, name: str) -> Optional[str]:
        """Retrieve secret from cloud provider with caching."""
        async with self._lock:
            # Check cache
            if name in self._cache:
                value, timestamp = self._cache[name]
                if asyncio.get_event_loop().time() - timestamp < self._cache_ttl:
                    return value

            # Fetch from provider
            result = None
            if self.provider == "aws":
                result = await self._get_aws_secret(name)
            elif self.provider == "azure":
                result = await self._get_azure_secret(name)
            elif self.provider == "gcp":
                result = await self._get_gcp_secret(name)
            elif self.provider == "hashicorp":
                result = await self._get_vault_secret(name)
            elif self.provider == "local":
                from hopefx.config.vault import vault
                result = vault.retrieve(name)

            # Update cache
            if result:
                self._cache[name] = (result, asyncio.get_event_loop().time())

            return result

    async def _get_aws_secret(self, name: str) -> Optional[str]:
        """AWS Secrets Manager implementation."""
        try:
            if not self._client:
                self._client = boto3.client(
                    'secretsmanager',
                    region_name=settings.aws_region
                )

            response = self._client.get_secret_value(SecretId=name)
            
            if 'SecretString' in response:
                return response['SecretString']
            else:
                import base64
                return base64.b64decode(response['SecretBinary']).decode()
                
        except ClientError as e:
            logger.error("aws_secrets.error", name=name, error=str(e))
            return None

    async def _get_azure_secret(self, name: str) -> Optional[str]:
        """Azure Key Vault implementation."""
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            if not self._client:
                credential = DefaultAzureCredential()
                self._client = SecretClient(
                    vault_url=settings.azure_keyvault_url,
                    credential=credential
                )

            secret = await asyncio.to_thread(self._client.get_secret, name)
            return secret.value
            
        except Exception as e:
            logger.error("azure_secrets.error", name=name, error=str(e))
            return None

    async def _get_gcp_secret(self, name: str) -> Optional[str]:
        """GCP Secret Manager implementation."""
        try:
            from google.cloud import secretmanager

            if not self._client:
                self._client = secretmanager.SecretManagerServiceClient()

            project_id = settings.gcp_project_id
            secret_path = f"projects/{project_id}/secrets/{name}/versions/latest"

            response = await asyncio.to_thread(
                self._client.access_secret_version,
                request={"name": secret_path}
            )
            
            return response.payload.data.decode("UTF-8")
            
        except Exception as e:
            logger.error("gcp_secrets.error", name=name, error=str(e))
            return None

    async def _get_vault_secret(self, name: str) -> Optional[str]:
        """HashiCorp Vault implementation."""
        try:
            import hvac

            if not self._client:
                self._client = hvac.Client(
                    url=settings.vault_url,
                    token=settings.vault_token
                )

            secret = await asyncio.to_thread(
                self._client.secrets.kv.v2.read_secret_version,
                path=name,
                mount_point=settings.vault_mount_point
            )
            
            return secret["data"]["data"]["value"]
            
        except Exception as e:
            logger.error("vault_secrets.error", name=name, error=str(e))
            return None

    async def rotate_secret(self, name: str) -> bool:
        """Trigger cloud secret rotation."""
        try:
            if self.provider == "aws":
                await asyncio.to_thread(
                    self._client.rotate_secret,
                    SecretId=name
                )
                return True
            return False
        except Exception as e:
            logger.error("secret_rotation.failed", name=name, error=str(e))
            return False

    async def create_secret(self, name: str, value: str) -> bool:
        """Create new secret in cloud provider."""
        try:
            if self.provider == "aws":
                await asyncio.to_thread(
                    self._client.create_secret,
                    Name=name,
                    SecretString=value
                )
                return True
            return False
        except Exception as e:
            logger.error("secret_create.failed", name=name, error=str(e))
            return False


# Global instance
cloud_secrets = CloudSecretsManager()

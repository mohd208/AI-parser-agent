import json
from functools import lru_cache

import boto3

from .config import settings

_client = boto3.client("secretsmanager", region_name=settings.aws_region)


@lru_cache(maxsize=8)
def get_secret(environment: str) -> dict:
    """Fetch the environment-specific secret bundle (GitHub token, Datadog keys,
    AWS/EKS identifiers) from AWS Secrets Manager. Cached per-process; restart
    the service after rotating a secret.
    """
    name = settings.secret_name_template.format(environment=environment)
    resp = _client.get_secret_value(SecretId=name)
    return json.loads(resp["SecretString"])

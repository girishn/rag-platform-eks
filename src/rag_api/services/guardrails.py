import boto3
from src.rag_api.config import settings

_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)


def apply_guardrail(text: str, source: str = "INPUT") -> str:
    """Apply Bedrock Guardrails. Returns the text if approved, raises on violation."""
    if not settings.bedrock_guardrail_id:
        return text

    response = _client.apply_guardrail(
        guardrailIdentifier=settings.bedrock_guardrail_id,
        guardrailVersion="DRAFT",
        source=source,
        content=[{"text": {"text": text}}],
    )

    if response["action"] == "GUARDRAIL_INTERVENED":
        raise ValueError(f"Guardrail intervened: {response.get('outputs', [])}")

    return text

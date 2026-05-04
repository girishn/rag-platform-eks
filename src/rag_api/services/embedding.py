import json
import boto3
from src.rag_api.config import settings

_client = boto3.client("bedrock-runtime", region_name=settings.aws_region)


async def embed(text: str) -> list[float]:
    response = _client.invoke_model(
        modelId=settings.bedrock_embedding_model_id,
        body=json.dumps({"inputText": text}),
        contentType="application/json",
        accept="application/json",
    )
    body = json.loads(response["body"].read())
    return body["embedding"]  # type: ignore[no-any-return]

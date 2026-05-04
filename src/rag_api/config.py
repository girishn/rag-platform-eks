from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # AWS
    aws_region: str = "ap-southeast-2"
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_guardrail_id: str = ""

    # Database
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "ragplatform"
    db_user: str = "ragapi"
    db_password: str = ""
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    # LiteLLM
    litellm_base_url: str = "http://litellm:4000"
    litellm_api_key: str = ""

    # Observability
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"


settings = Settings()

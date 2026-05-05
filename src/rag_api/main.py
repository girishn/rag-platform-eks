from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import make_asgi_app
from fastapi import FastAPI

from src.rag_api.config import settings
from src.rag_api.logging_config import configure_logging
from src.rag_api.routers import chat

configure_logging()

_resource = Resource(attributes={SERVICE_NAME: "rag-api"})
_provider = TracerProvider(resource=_resource)
_provider.add_span_processor(
    BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
)
trace.set_tracer_provider(_provider)

app = FastAPI(title="RAG Platform API", version="0.1.0")
FastAPIInstrumentor.instrument_app(app)

app.include_router(chat.router)

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

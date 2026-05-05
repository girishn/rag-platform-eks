"""Ingestion pipeline entrypoint. Run as a Kubernetes CronJob."""
import asyncio
import logging
import os

from src.ingestion.pipeline import CHUNK_OVERLAP, CHUNK_SIZE, EMBED_BATCH_SIZE, run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    tenant_id = os.environ["TENANT_ID"]
    s3_bucket = os.environ["S3_BUCKET"]
    s3_prefix = os.environ.get("S3_PREFIX", f"{tenant_id}/raw/")

    logger.info(
        "Starting ingestion tenant=%s bucket=%s prefix=%s chunk_size=%d overlap=%d embed_batch=%d",
        tenant_id, s3_bucket, s3_prefix, CHUNK_SIZE, CHUNK_OVERLAP, EMBED_BATCH_SIZE,
    )
    asyncio.run(run_pipeline(tenant_id=tenant_id, s3_bucket=s3_bucket, s3_prefix=s3_prefix))
    logger.info("Ingestion complete")


if __name__ == "__main__":
    main()

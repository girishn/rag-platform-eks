"""Document text extraction.

Two-tier strategy:
  - unstructured: native digital documents (PDF with text layer, DOCX, PPTX, XLSX, HTML, Markdown)
  - Textract sync:  single-page image files (JPEG, PNG, TIFF)
  - Textract async: scanned PDFs — detected when unstructured returns < 200 chars from a PDF,
                    meaning the PDF has no text layer; Textract reads it from S3 directly.
"""
import io
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3

logger = logging.getLogger(__name__)

_UNSTRUCTURED_EXTS = frozenset({
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".csv",
    ".html", ".htm", ".xml",
    ".md", ".rst", ".txt", ".rtf",
})
_TEXTRACT_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".tiff", ".tif"})

# Scanned PDF heuristic: if unstructured extracts fewer than this many chars, assume no text layer.
_SCANNED_PDF_THRESHOLD = 200


def extract_text(
    *,
    s3_key: str,
    raw_bytes: bytes,
    s3_bucket: str,
    textract: "boto3.client",
) -> str:
    """Return plain text from a document. Returns empty string for unsupported formats."""
    ext = Path(s3_key).suffix.lower()

    if ext in _TEXTRACT_IMAGE_EXTS:
        logger.info("Parsing image via Textract sync: %s", s3_key)
        return _textract_sync(textract, raw_bytes)

    if ext in _UNSTRUCTURED_EXTS:
        text = _unstructured(raw_bytes, ext)
        if ext == ".pdf" and len(text.strip()) < _SCANNED_PDF_THRESHOLD:
            logger.info(
                "PDF yielded %d chars via unstructured — likely scanned, falling back to Textract: %s",
                len(text.strip()), s3_key,
            )
            return _textract_async(textract, s3_bucket, s3_key)
        return text

    logger.warning("No parser for extension '%s', skipping: %s", ext or "(none)", s3_key)
    return ""


def _unstructured(raw_bytes: bytes, ext: str) -> str:
    from unstructured.partition.auto import partition  # lazy: only loaded when needed

    elements = partition(file=io.BytesIO(raw_bytes), metadata_filename=f"doc{ext}")
    return "\n\n".join(str(el) for el in elements if str(el).strip())


def _textract_sync(textract: "boto3.client", raw_bytes: bytes) -> str:
    response = textract.detect_document_text(Document={"Bytes": raw_bytes})
    return "\n".join(
        block["Text"]
        for block in response["Blocks"]
        if block["BlockType"] == "LINE"
    )


def _textract_async(textract: "boto3.client", s3_bucket: str, s3_key: str) -> str:
    """Async Textract job for multi-page scanned PDFs. Document is read from S3 directly."""
    job = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": s3_bucket, "Name": s3_key}}
    )
    job_id: str = job["JobId"]
    logger.info("Textract async job %s started for s3://%s/%s", job_id, s3_bucket, s3_key)

    while True:
        result = textract.get_document_text_detection(JobId=job_id)
        status: str = result["JobStatus"]
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(
                f"Textract job {job_id} failed for s3://{s3_bucket}/{s3_key}: "
                f"{result.get('StatusMessage', 'no detail')}"
            )
        time.sleep(5)

    lines: list[str] = []
    while True:
        for block in result["Blocks"]:
            if block["BlockType"] == "LINE":
                lines.append(block["Text"])
        next_token: str | None = result.get("NextToken")
        if not next_token:
            break
        result = textract.get_document_text_detection(JobId=job_id, NextToken=next_token)

    return "\n".join(lines)

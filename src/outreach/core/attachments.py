"""Immutable email files and the local campaign attachment limits."""

from __future__ import annotations

import hashlib
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS = 5
FILE_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def upload_name(value: str) -> str:
    name = value.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if any(code in name.casefold() for code in ("%00", "%0a", "%0d")):
        raise ValueError("Choose a filename without encoded control characters.")
    if not name or len(name) > 180 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Choose a file with a simple filename, up to 180 characters.")
    if PurePosixPath(name).suffix.casefold() not in FILE_TYPES:
        raise ValueError("Use PDF, DOCX, XLSX, PPTX, TXT, CSV, PNG or JPG files.")
    return name


class EmailAttachment(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    filename: str
    mime_type: str
    content: bytes = Field(repr=False)

    @model_validator(mode="after")
    def valid_file(self):
        if upload_name(self.filename) != self.filename:
            raise ValueError("Invalid attachment filename.")
        if self.mime_type != FILE_TYPES[PurePosixPath(self.filename).suffix.casefold()]:
            raise ValueError("Invalid attachment type.")
        if not 0 < len(self.content) <= MAX_ATTACHMENT_BYTES:
            raise ValueError("Attachments must be non-empty and total at most 10 MB.")
        return self

    def manifest(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
        }


def validate_bundle(files):
    if len(files) > MAX_ATTACHMENTS or sum(len(f.content) for f in files) > MAX_ATTACHMENT_BYTES:
        raise ValueError("Use at most 5 attachments, with a combined size of 10 MB.")
    return tuple(files)


def manifests(files):
    return [file.manifest() for file in files]

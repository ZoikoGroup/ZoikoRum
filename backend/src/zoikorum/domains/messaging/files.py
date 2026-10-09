"""Conservative file allowlist. No executable, macro or active HTML uploads."""
import io
import zipfile
from pathlib import PurePath

from zoikorum.shared.errors import ValidationFailed


def validate_file(name: str, data: bytes) -> str:
    ext = PurePath(name).suffix.lower()
    if ext == ".pdf" and data.startswith(b"%PDF-"):
        if any(token in data.lower() for token in (b"/javascript", b"/js", b"/launch", b"/embeddedfile")):
            raise ValidationFailed("Active PDF content is not allowed")
        return "application/pdf"
    if ext == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if ext in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if ext in {".txt", ".csv"}:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailed("Text files must use UTF-8") from exc
        if "\x00" in text:
            raise ValidationFailed("Binary data is not a text file")
        return "text/plain" if ext == ".txt" else "text/csv"
    if ext in {".docx", ".xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                names = [i.filename.lower() for i in entries]
                if len(entries) > 2000 or sum(i.file_size for i in entries) > 50 * 1024 * 1024:
                    raise ValidationFailed("Document expands beyond the supported size")
                if any("vbaproject" in n or "activex" in n or "embeddings/" in n or ".." in n.split("/") for n in names):
                    raise ValidationFailed("Active or embedded document content is not allowed")
                if "[content_types].xml" not in names or ("word/document.xml" if ext == ".docx" else "xl/workbook.xml") not in names:
                    raise ValidationFailed("Invalid Office document")
            return "application/vnd.openxmlformats-officedocument." + ("wordprocessingml.document" if ext == ".docx" else "spreadsheetml.sheet")
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ValidationFailed("Invalid Office document") from exc
    raise ValidationFailed("Supported files: PDF, DOCX, XLSX, PNG, JPEG, TXT and CSV")

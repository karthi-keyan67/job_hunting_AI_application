import io
import re
import zipfile

import fitz
from docx import Document


class InvalidResume(ValueError):
    pass


def parse_resume(content: bytes, extension: str) -> dict:
    if extension == "pdf":
        if not content.startswith(b"%PDF-"):
            raise InvalidResume("The uploaded file is not a valid PDF")
        try:
            with fitz.open(stream=content, filetype="pdf") as pdf:
                if pdf.is_encrypted or len(pdf) == 0 or len(pdf) > 500:
                    raise InvalidResume("The PDF is encrypted or has an unsupported page count")
                text = "\n".join(page.get_text() for page in pdf).strip()
        except InvalidResume:
            raise
        except Exception as exc:
            raise InvalidResume("The PDF could not be read") from exc
        if len(re.sub(r"\s", "", text)) < 40:
            return {"text": text, "data": {}, "status": "NEEDS_OCR", "error": "This PDF has no extractable text; OCR is not enabled."}
    elif extension == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if len(archive.namelist()) > 1000 or sum(x.file_size for x in archive.infolist()) > 25_000_000:
                    raise InvalidResume("The DOCX document exceeds supported limits")
                if "[Content_Types].xml" not in archive.namelist() or "word/document.xml" not in archive.namelist():
                    raise InvalidResume("The uploaded file is not a valid DOCX document")
            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        except InvalidResume:
            raise
        except Exception as exc:
            raise InvalidResume("The DOCX document could not be read") from exc
        if not text:
            raise InvalidResume("The document contains no readable text")
    else:
        raise InvalidResume("Only PDF and DOCX resumes are supported")

    sections: dict[str, list[str]] = {}
    active: str | None = None
    section_aliases = {
        "skills": ("skills", "technicalexpertise", "technologies"),
        "experience": ("experience", "employment", "workhistory", "professionalexperience"),
        "education": ("education", "academicbackground"),
        "certifications": ("certification", "certifications"),
        "projects": ("projects", "selectedprojects"),
    }
    heading_values = {alias: section for section, aliases in section_aliases.items() for alias in aliases}
    name: str | None = None
    for line in text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        heading = re.sub(r"[^a-z]", "", cleaned.lower())
        section = heading_values.get(heading)
        if section:
            active = section
            sections.setdefault(section, [])
        elif heading in {"summary", "profile", "objective", "contact", "personalprofile"}:
            active = None
        else:
            if name is None and "@" not in cleaned and len(cleaned) <= 100 and not re.search(r"\d{3}", cleaned):
                name = cleaned
            if active is not None:
                sections[active].append(cleaned)
    emails = list(dict.fromkeys(re.findall(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)))
    phones = list(dict.fromkeys(re.findall(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", text)))
    return {
        "text": text,
        "data": {"name": name, "emails": emails, "phone_numbers": phones, **sections},
        "status": "COMPLETED",
        "error": None,
    }

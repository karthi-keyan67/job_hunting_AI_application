import io

import fitz
import pytest
from docx import Document


async def auth(client, email="resume@example.com"):
    response = await client.post("/api/v1/auth/register", json={"email": email, "password": "correct-horse-battery-1"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def pdf_bytes(text="Jordan Example\njordan@example.com\nSkills\nPython, FastAPI\nExperience\nBackend Engineer 2022-2025"):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def docx_bytes():
    doc = Document()
    doc.add_paragraph("Casey Example")
    doc.add_paragraph("casey@example.com")
    doc.add_heading("Skills", level=1)
    doc.add_paragraph("Python, SQL")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


@pytest.mark.asyncio
async def test_resume_upload_parse_download_versions_default_and_delete(client):
    headers = await auth(client)
    first_file = pdf_bytes()
    created = await client.post("/api/v1/resumes", headers=headers, data={"title": "Backend CV"}, files={"file": ("resume.pdf", first_file, "application/pdf")})
    assert created.status_code == 201, created.text
    resume = created.json()
    assert resume["is_default"] is True
    first = resume["versions"][0]
    assert first["version_number"] == 1
    assert first["parsing_status"] == "COMPLETED"
    assert first["parsed_data"]["name"] == "Jordan Example"
    assert "jordan@example.com" in first["parsed_data"]["emails"]
    assert first["parsed_data"]["skills"]

    duplicate = await client.post(f"/api/v1/resumes/{resume['id']}/versions", headers=headers, files={"file": ("same.pdf", first_file, "application/pdf")})
    assert duplicate.status_code == 409
    second_file = docx_bytes()
    second = await client.post(f"/api/v1/resumes/{resume['id']}/versions", headers=headers, files={"file": ("latest.docx", second_file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert second.status_code == 201, second.text
    assert [version["version_number"] for version in second.json()["versions"]] == [2, 1]
    assert second.json()["versions"][0]["parsing_status"] == "COMPLETED"

    download = await client.get(f"/api/v1/resumes/{resume['id']}/versions/{second.json()['versions'][0]['id']}/download", headers=headers)
    assert download.status_code == 200 and download.content == second_file

    other = await client.post("/api/v1/resumes", headers=await auth(client, "other@example.com"), files={"file": ("other.pdf", pdf_bytes(), "application/pdf")})
    assert other.status_code == 201 and other.json()["is_default"] is True
    default = await client.post(f"/api/v1/resumes/{resume['id']}/default", headers=headers)
    assert default.status_code == 200 and default.json()["is_default"] is True
    assert (await client.get(f"/api/v1/resumes/{resume['id']}", headers=await auth(client, "third@example.com"))).status_code == 404

    deleted_version = await client.delete(f"/api/v1/resumes/{resume['id']}/versions/{second.json()['versions'][0]['id']}", headers=headers)
    assert deleted_version.status_code == 204
    deleted = await client.delete(f"/api/v1/resumes/{resume['id']}", headers=headers)
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_resume_upload_validation_and_auth(client):
    unauthorized = await client.get("/api/v1/resumes")
    assert unauthorized.status_code == 401
    headers = await auth(client)
    invalid_type = await client.post("/api/v1/resumes", headers=headers, files={"file": ("resume.exe", b"MZ", "application/octet-stream")})
    assert invalid_type.status_code == 415
    invalid_pdf = await client.post("/api/v1/resumes", headers=headers, files={"file": ("resume.pdf", b"not a pdf", "application/pdf")})
    assert invalid_pdf.status_code == 422
    empty = await client.post("/api/v1/resumes", headers=headers, files={"file": ("empty.pdf", b"", "application/pdf")})
    assert empty.status_code == 422


@pytest.mark.asyncio
async def test_scanned_pdf_records_needs_ocr(client):
    headers = await auth(client)
    response = await client.post("/api/v1/resumes", headers=headers, files={"file": ("scan.pdf", pdf_bytes(""), "application/pdf")})
    assert response.status_code == 201, response.text
    version = response.json()["versions"][0]
    assert version["parsing_status"] == "NEEDS_OCR"

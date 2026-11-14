import hashlib
import logging
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.account import Resume, ResumeVersion, User
from app.models.enums import ResumeParsingStatus
from app.repositories.resume import ResumeRepository
from app.services.resume_parser import InvalidResume, parse_resume
from app.services.resume_storage import LocalResumeStorage

logger = logging.getLogger(__name__)


class ResumeService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = ResumeRepository(session)
        self.settings = get_settings()
        self.storage = LocalResumeStorage(self.settings.resume_storage_root)

    @staticmethod
    def safe_filename(filename: str | None) -> str:
        name = (filename or "resume").replace("\\", "/").split("/")[-1]
        name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
        return name[:255] or "resume"

    async def read_upload(self, upload: UploadFile) -> tuple[bytes, str, str]:
        filename = self.safe_filename(upload.filename)
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in {"pdf", "docx"}:
            raise HTTPException(status_code=415, detail="Only PDF and DOCX resumes are supported")
        chunks: list[bytes] = []
        total = 0
        while chunk := await upload.read(65536):
            total += len(chunk)
            if total > self.settings.max_resume_upload_bytes:
                raise HTTPException(status_code=413, detail="Resume exceeds the upload size limit")
            chunks.append(chunk)
        content = b"".join(chunks)
        if not content:
            raise HTTPException(status_code=422, detail="Resume file is empty")
        try:
            parse_resume(content, ext)
        except InvalidResume as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return content, filename, ext

    async def create(self, user: User, upload: UploadFile, title: str | None) -> Resume:
        content, filename, ext = await self.read_upload(upload)
        await self.session.scalar(select(User).where(User.id == user.id).with_for_update())
        key = self.storage.save(content, ext)
        resume = Resume(user_id=user.id, title=(title or Path(filename).stem)[:200] or "Resume", is_default=False)
        try:
            self.session.add(resume)
            await self.session.flush()
            existing = await self.session.scalar(select(Resume.id).where(Resume.user_id == user.id, Resume.is_default.is_(True)))
            resume.is_default = existing is None
            version = self._version(resume.id, 1, filename, key, ext, content)
            self.session.add(version)
            await self.session.flush()
            await self._parse(version, content, ext)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self.storage.delete(key)
            raise
        return await self._loaded(resume.id, user.id)

    async def add_version(self, user_id: UUID, resume_id: UUID, upload: UploadFile, force: bool) -> Resume:
        content, filename, ext = await self.read_upload(upload)
        resume = await self.repo.get(resume_id, user_id, lock=True)
        if not resume:
            raise HTTPException(status_code=404, detail="Resume not found")
        digest = hashlib.sha256(content).hexdigest()
        if not force and any(version.file_hash == digest for version in resume.versions):
            raise HTTPException(status_code=409, detail="This file already exists as a version. Set force_new_version=true to keep another copy.")
        next_version = max((item.version_number for item in resume.versions), default=0) + 1
        key = self.storage.save(content, ext)
        try:
            version = self._version(resume.id, next_version, filename, key, ext, content)
            self.session.add(version)
            await self.session.flush()
            await self._parse(version, content, ext)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            self.storage.delete(key)
            raise
        return await self._loaded(resume.id, user_id)

    def _version(self, resume_id: UUID, number: int, filename: str, key: str, ext: str, content: bytes) -> ResumeVersion:
        return ResumeVersion(
            resume_id=resume_id, version_number=number, original_filename=filename, storage_key=key,
            file_type=ext.upper(), file_size=len(content), file_hash=hashlib.sha256(content).hexdigest(),
            parsing_status=ResumeParsingStatus.PROCESSING,
        )

    async def _parse(self, version: ResumeVersion, content: bytes, ext: str) -> None:
        try:
            result = parse_resume(content, ext)
            version.parsed_text = result["text"]
            version.parsed_data = result["data"]
            version.parsing_status = ResumeParsingStatus(result["status"])
            version.parsing_error = result["error"]
        except Exception:
            logger.exception("Resume parsing failed for version %s", version.id)
            version.parsing_status = ResumeParsingStatus.FAILED
            version.parsing_error = "The resume was stored but could not be parsed."
        await self.session.flush()

    async def _loaded(self, resume_id: UUID, user_id: UUID) -> Resume:
        resume = await self.repo.get(resume_id, user_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        return resume

    async def list(self, user_id: UUID) -> list[Resume]:
        return await self.repo.list_for_user(user_id)

    async def get(self, resume_id: UUID, user_id: UUID) -> Resume:
        resume = await self.repo.get(resume_id, user_id)
        if resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        return resume

    async def set_default(self, resume_id: UUID, user_id: UUID) -> Resume:
        await self.session.scalar(select(User).where(User.id == user_id).with_for_update())
        resume = await self.repo.get(resume_id, user_id, lock=True)
        if resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        await self.session.execute(select(Resume).where(Resume.user_id == user_id, Resume.is_default.is_(True)).with_for_update())
        from sqlalchemy import update
        await self.session.execute(update(Resume).where(Resume.user_id == user_id).values(is_default=False))
        resume.is_default = True
        await self.session.commit()
        return await self.get(resume_id, user_id)

    async def download(self, user_id: UUID, resume_id: UUID, version_id: UUID):
        resume = await self.repo.get(resume_id, user_id)
        version = await self.repo.get_version(resume_id, version_id)
        if resume is None or version is None:
            raise HTTPException(status_code=404, detail="Resume version not found")
        try:
            path = self.storage.path_for(version.storage_key)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Resume file not found") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Resume file not found")
        media = "application/pdf" if version.file_type == "PDF" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return FileResponse(path, media_type=media, filename=version.original_filename)

    async def delete(self, user_id: UUID, resume_id: UUID) -> None:
        resume = await self.repo.get(resume_id, user_id, lock=True)
        if resume is None:
            raise HTTPException(status_code=404, detail="Resume not found")
        for version in resume.versions:
            if await self._is_referenced(version.id):
                raise HTTPException(status_code=409, detail="This resume is referenced by application data")
        keys = [version.storage_key for version in resume.versions]
        await self.session.delete(resume)
        await self.session.commit()
        for key in keys:
            try:
                self.storage.delete(key)
            except OSError:
                logger.exception("Unable to remove stored resume file")

    async def delete_version(self, user_id: UUID, resume_id: UUID, version_id: UUID) -> None:
        resume = await self.repo.get(resume_id, user_id, lock=True)
        version = await self.repo.get_version(resume_id, version_id)
        if resume is None or version is None:
            raise HTTPException(status_code=404, detail="Resume version not found")
        if len(resume.versions) <= 1:
            raise HTTPException(status_code=409, detail="Delete the resume to remove its final version")
        if await self._is_referenced(version_id):
            raise HTTPException(status_code=409, detail="This resume version is referenced by application data")
        key = version.storage_key
        await self.session.delete(version)
        await self.session.commit()
        try:
            self.storage.delete(key)
        except OSError:
            logger.exception("Unable to remove stored resume file")

    async def _is_referenced(self, version_id: UUID) -> bool:
        from app.models.applications import ApplicationDraft, ApplicationEvent, ApplicationAuditLog
        from sqlalchemy import cast, String
        ref = str(version_id)
        for query in (
            select(ApplicationDraft.id).where(cast(ApplicationDraft.content, String).contains(ref)),
            select(ApplicationEvent.id).where(cast(ApplicationEvent.metadata_json, String).contains(ref)),
            select(ApplicationAuditLog.id).where(cast(ApplicationAuditLog.details, String).contains(ref)),
        ):
            if await self.session.scalar(query.limit(1)):
                return True
        return False

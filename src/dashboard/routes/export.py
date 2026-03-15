"""Export page and download routes.

Export generation is kept synchronous (the design choice for Phase 6 MVP):
the export runners are fast relative to scrape/extract, and the simplicity
of a direct call outweighs any benefit of backgrounding it.

Long-running pipeline stages (scrape, extract, verify, score) use the async
task runner; export does not need to.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.config.settings import settings
from src.dashboard.deps import templates
from src.db.session import get_session
from src.export.runner import run_export_for_campaign
from src.models.campaign import Campaign
from src.models.company_lead import CompanyLead
from src.models.enums import LeadStatus, ReviewStatus
from sqlalchemy import func, select

router = APIRouter()


def _list_previous_exports(campaign_id: uuid.UUID) -> list[dict]:
    """Return a list of previously generated export files, newest first."""
    export_dir = Path(settings.export_dir) / str(campaign_id)
    if not export_dir.exists():
        return []

    files = sorted(export_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "mtime": f.stat().st_mtime,
        }
        for f in files
        if f.suffix == ".csv"
    ]


def _get_lead_summary(session, campaign_id: uuid.UUID) -> dict:
    """Count approved leads by status for the export summary bar."""
    counts: dict[str, int] = {}
    for status in (
        LeadStatus.QUALIFIED,
        LeadStatus.CONTACTED,
        LeadStatus.CONVERTED,
    ):
        counts[status.value] = session.scalar(
            select(func.count()).select_from(CompanyLead).where(
                CompanyLead.campaign_id == campaign_id,
                CompanyLead.review_status == ReviewStatus.APPROVED,
                CompanyLead.status == status,
            )
        ) or 0
    counts["total"] = sum(counts.values())
    return counts


@router.get("/campaigns/{campaign_id}/export", response_class=HTMLResponse)
async def export_page(request: Request, campaign_id: uuid.UUID) -> HTMLResponse:
    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            return HTMLResponse("Campaign not found", status_code=404)
        lead_summary = _get_lead_summary(session, campaign_id)

    previous = _list_previous_exports(campaign_id)

    return templates.TemplateResponse(
        request,
        "export/index.html",
        {
            "campaign": campaign,
            "lead_summary": lead_summary,
            "previous": previous,
            "generated": None,
            "error": None,
        },
    )


@router.post("/campaigns/{campaign_id}/export/generate", response_class=HTMLResponse)
async def export_generate(request: Request, campaign_id: uuid.UUID) -> HTMLResponse:
    """Generate all three CSVs synchronously and return the export page with download links."""
    with get_session() as session:
        campaign = session.get(Campaign, campaign_id)
        if campaign is None:
            return HTMLResponse("Campaign not found", status_code=404)
        lead_summary = _get_lead_summary(session, campaign_id)

    error: str | None = None
    generated: dict | None = None

    try:
        summary = run_export_for_campaign(campaign_id)
        generated = {
            "contacts_file": Path(summary.contacts_file).name if summary.contacts_file else None,
            "companies_file": Path(summary.companies_file).name if summary.companies_file else None,
            "leads_file": Path(summary.leads_file).name if summary.leads_file else None,
            "contacts_rows": summary.contacts_rows,
            "companies_rows": summary.companies_rows,
            "leads_rows": summary.leads_rows,
        }
    except Exception as exc:
        error = str(exc)

    previous = _list_previous_exports(campaign_id)

    return templates.TemplateResponse(
        request,
        "export/index.html",
        {
            "campaign": campaign,
            "lead_summary": lead_summary,
            "previous": previous,
            "generated": generated,
            "error": error,
        },
    )


@router.get("/campaigns/{campaign_id}/export/download")
async def export_download(campaign_id: uuid.UUID, file: str) -> FileResponse:
    """Serve a named CSV export file.

    The ``file`` query parameter is validated to be a plain filename (no path
    components) within the campaign's export directory, preventing path traversal.
    """
    # Security: reject any path traversal attempts
    if "/" in file or "\\" in file or ".." in file:
        return HTMLResponse("Invalid file name", status_code=400)

    export_dir = Path(settings.export_dir) / str(campaign_id)
    file_path = export_dir / file

    if not file_path.exists() or not file_path.is_file():
        return HTMLResponse("File not found", status_code=404)

    # Confirm the resolved path is still within the export dir
    if not str(file_path.resolve()).startswith(str(export_dir.resolve())):
        return HTMLResponse("Access denied", status_code=403)

    return FileResponse(
        path=str(file_path),
        media_type="text/csv",
        filename=file,
    )

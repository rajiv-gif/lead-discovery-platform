"""leads — command-line interface for the lead discovery platform.

Each sub-command maps to one pipeline stage.
Run ``leads --help`` or ``leads <command> --help`` for usage.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.db.session import get_session
from src.discovery.runner import run_discovery_for_campaign
from src.export.runner import ExportSummary, run_export_for_campaign
from src.extraction.runner import ExtractionSummary, run_extraction_for_campaign
from src.models.campaign import Campaign
from src.models.enums import CampaignStatus, GeoMethod
from src.pipeline.runner import STAGES, PipelineSummary, run_pipeline
from src.scraper.runner import ScrapeSummary, run_scrape_for_campaign
from src.scoring.deriver import mark_contacted, mark_converted, mark_churned
from src.verification.runner import VerificationSummary, run_verification_for_campaign
from src.scoring.runner import ScoringRunSummary, run_scoring_for_campaign
from src.review.runner import run_review_for_campaign as _run_review_for_campaign

app = typer.Typer(
    name="leads",
    help="Lead discovery platform.",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Campaign management
# ---------------------------------------------------------------------------


@app.command()
def create_campaign(
    name: str = typer.Argument(..., help="Campaign name."),
    geo_method: str = typer.Option(
        ..., "--geo-method", "-g",
        help="Geo targeting method: city | postal_code | bounding_box | center_radius",
    ),
    specialty: str = typer.Option(
        "dentists", "--specialty", "-s",
        help="Business type to search for (default: dentists).",
    ),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Campaign description."),
    # city / postal_code options
    city: Optional[str] = typer.Option(None, "--city", help="City name (required for city mode)."),
    country: Optional[str] = typer.Option(None, "--country", help="Country (required for city mode)."),
    postal_code: Optional[str] = typer.Option(None, "--postal-code", help="Postal code (required for postal_code mode)."),
    # bounding_box options
    sw_lat: Optional[float] = typer.Option(None, "--sw-lat", help="Bounding box SW corner latitude."),
    sw_lng: Optional[float] = typer.Option(None, "--sw-lng", help="Bounding box SW corner longitude."),
    ne_lat: Optional[float] = typer.Option(None, "--ne-lat", help="Bounding box NE corner latitude."),
    ne_lng: Optional[float] = typer.Option(None, "--ne-lng", help="Bounding box NE corner longitude."),
    # center_radius options
    center_lat: Optional[float] = typer.Option(None, "--center-lat", help="Centre latitude (center_radius mode)."),
    center_lng: Optional[float] = typer.Option(None, "--center-lng", help="Centre longitude (center_radius mode)."),
    radius_m: Optional[int] = typer.Option(None, "--radius-m", help="Search radius in metres (center_radius mode)."),
) -> None:
    """Create a new discovery campaign with geo targeting.

    Examples:

    \b
    leads create-campaign "London Dentists" --geo-method city --city London --country UK
    leads create-campaign "SW1 Dentists"   --geo-method postal_code --postal-code SW1A1AA
    leads create-campaign "Central London" --geo-method center_radius \\
        --center-lat 51.5074 --center-lng -0.1278 --radius-m 5000
    """
    # --- Parse and validate geo_method ---
    try:
        geo_method_enum = GeoMethod(geo_method)
    except ValueError:
        valid = ", ".join(m.value for m in GeoMethod)
        console.print(f"[red]Error: invalid --geo-method {geo_method!r}. Valid values: {valid}[/red]")
        raise typer.Exit(1)

    # --- Validate required fields per method ---
    validation_error: Optional[str] = None
    if geo_method_enum == GeoMethod.CITY:
        if not city or not country:
            validation_error = "--city and --country are required for city mode"
    elif geo_method_enum == GeoMethod.POSTAL_CODE:
        if not postal_code:
            validation_error = "--postal-code is required for postal_code mode"
    elif geo_method_enum == GeoMethod.BOUNDING_BOX:
        if any(v is None for v in (sw_lat, sw_lng, ne_lat, ne_lng)):
            validation_error = "--sw-lat, --sw-lng, --ne-lat, --ne-lng are all required for bounding_box mode"
        elif sw_lat >= ne_lat or sw_lng >= ne_lng:  # type: ignore[operator]
            validation_error = (
                "--sw-lat must be less than --ne-lat and --sw-lng must be less than --ne-lng "
                "(SW corner must be south-west of NE corner)"
            )
    elif geo_method_enum == GeoMethod.CENTER_RADIUS:
        if any(v is None for v in (center_lat, center_lng, radius_m)):
            validation_error = "--center-lat, --center-lng, --radius-m are all required for center_radius mode"
        elif radius_m is not None and radius_m <= 0:
            validation_error = "--radius-m must be a positive integer"
        elif radius_m is not None and radius_m > 50_000:
            validation_error = "--radius-m must be ≤ 50,000 m (50 km — Places API maximum)"

    if validation_error:
        console.print(f"[red]Error: {validation_error}[/red]")
        raise typer.Exit(1)

    # --- Persist campaign ---
    with get_session() as session:
        campaign = Campaign(
            name=name,
            description=description,
            status=CampaignStatus.DRAFT,
            geo_method=geo_method_enum,
            specialty=specialty,
            geo_city=city,
            geo_country=country,
            geo_postal_code=postal_code,
            geo_sw_lat=sw_lat,
            geo_sw_lng=sw_lng,
            geo_ne_lat=ne_lat,
            geo_ne_lng=ne_lng,
            geo_center_lat=center_lat,
            geo_center_lng=center_lng,
            geo_radius_m=radius_m,
        )
        session.add(campaign)
        session.flush()
        campaign_id = str(campaign.id)

    console.print(f"\n[green]Campaign created[/green]")
    console.print(f"  ID:         [bold]{campaign_id}[/bold]")
    console.print(f"  Name:       {name}")
    console.print(f"  Geo method: {geo_method_enum.value}")
    console.print(f"  Specialty:  {specialty}")
    console.print(f"  Status:     draft\n")
    console.print(f"Run discovery with:")
    console.print(f"  [bold]leads run-discovery --campaign-id {campaign_id}[/bold]\n")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@app.command()
def run_discovery(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to run discovery for.",
    ),
) -> None:
    """Run Google Places discovery for a campaign.

    Queries the Google Places API using the campaign's geo configuration,
    upserts matching companies, and logs discovery hits.

    Requires GOOGLE_PLACES_API_KEY to be set in the environment.
    """
    # Validate UUID format
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Running discovery for campaign {cid}...[/bold]\n")

    try:
        summary = run_discovery_for_campaign(cid)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_discovery_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Pipeline stage stubs (implemented in later phases)
# ---------------------------------------------------------------------------


@app.command()
def scrape(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign whose pending hits to scrape.",
    ),
) -> None:
    """Fetch and persist pages for all pending discovery hits in a campaign.

    For each pending hit the scraper fetches the company homepage, discovers
    supplemental pages (About / Contact / Team), persists HTML to disk and
    metadata + extracted text to PostgreSQL, then marks the hit as scraped.

    Hits without a company website are marked as skipped.
    Hits whose homepage fetch fails are marked as failed.
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Running scrape for campaign {cid}...[/bold]\n")

    try:
        summary = run_scrape_for_campaign(cid)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_scrape_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


@app.command()
def extract(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign whose scraped hits to extract.",
    ),
) -> None:
    """Run extraction (deterministic + LLM) on scraped pages for a campaign.

    For each SCRAPED discovery hit, extracts contacts, emails, and phones from
    the company's persisted pages, then marks the hit as extracted.

    If ANTHROPIC_API_KEY is set and deterministic extraction finds no contacts,
    the LLM is invoked on the best available team/contact/about page.
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Running extraction for campaign {cid}...[/bold]\n")

    try:
        summary = run_extraction_for_campaign(cid)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_extraction_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


@app.command()
def verify(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to verify.",
    ),
) -> None:
    """Validate extracted lead fields (email, phone, URL) for a campaign.

    Email addresses are checked for format and MX record validity.
    Phone numbers are classified by type (mobile / office / unknown).
    Company websites are probed for HTTP reachability.

    Website results are saved to data/website_checks/<campaign-id>.json
    so the ``score`` command can consume them without a live network check.
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Running verification for campaign {cid}...[/bold]\n")

    try:
        summary, website_results = run_verification_for_campaign(cid)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    # Persist website results so score command can read them
    checks_dir = Path("data/website_checks")
    checks_dir.mkdir(parents=True, exist_ok=True)
    checks_file = checks_dir / f"{cid}.json"
    checks_file.write_text(
        json.dumps({str(k): v for k, v in website_results.items()}, indent=2)
    )

    _print_verification_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


@app.command()
def score(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to score.",
    ),
) -> None:
    """Score leads by quality for a campaign.

    Loads website reachability results from data/website_checks/<campaign-id>.json
    if available (produced by the ``verify`` command).
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    # Load website results if available
    checks_file = Path("data/website_checks") / f"{cid}.json"
    website_results: dict[uuid.UUID, bool] = {}
    if checks_file.exists():
        raw = json.loads(checks_file.read_text())
        website_results = {uuid.UUID(k): v for k, v in raw.items()}

    console.print(f"\n[bold]Running scoring for campaign {cid}...[/bold]\n")

    try:
        summary = run_scoring_for_campaign(cid, website_results=website_results)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_scoring_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


@app.command()
def review(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to review.",
    ),
    min_score: float = typer.Option(
        25.0, "--min-score",
        help="Minimum score threshold for review queue.",
    ),
) -> None:
    """Interactive human review of scored leads (approve / reject / edit / skip).

    Only leads with review_status=PENDING and score >= min_score are shown,
    ordered highest score first.
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Starting review for campaign {cid} (min_score={min_score})...[/bold]\n")

    try:
        result = _run_review_for_campaign(cid, min_score=min_score)
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Review complete[/bold]")
    console.print(f"  Reviewed:   {result.get('reviewed', 0)}")
    console.print(f"  Approved:   {result.get('approved', 0)}")
    console.print(f"  Rejected:   {result.get('rejected', 0)}")
    console.print(f"  Needs edit: {result.get('needs_edit', 0)}")
    console.print(f"  Skipped:    {result.get('skipped', 0)}\n")


@app.command()
def export(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to export.",
    ),
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir",
        help="Directory for CSV output. Defaults to data/exports.",
    ),
    only_uncontacted: bool = typer.Option(
        False, "--only-uncontacted",
        help="Exclude already-contacted leads.",
    ),
    include_converted: bool = typer.Option(
        False, "--include-converted",
        help="Include converted leads in export.",
    ),
) -> None:
    """Export approved leads to CSV files (contacts, companies, leads views)."""
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    out_path = Path(output_dir) if output_dir else None

    console.print(f"\n[bold]Exporting leads for campaign {cid}...[/bold]\n")

    try:
        summary = run_export_for_campaign(
            cid,
            export_dir=out_path,
            only_uncontacted=only_uncontacted,
            include_converted=include_converted,
        )
    except (RuntimeError, ValueError) as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_export_summary(summary)

    if summary.errors > 0:
        raise typer.Exit(1)


@app.command()
def run(
    campaign_id: str = typer.Option(
        ..., "--campaign-id", "-c",
        help="UUID of the campaign to run.",
    ),
    from_stage: str = typer.Option(
        "discover", "--from-stage",
        help=f"Start from this stage: {', '.join(STAGES)}",
    ),
    to_stage: str = typer.Option(
        "score", "--to-stage",
        help=f"Stop after this stage: {', '.join(STAGES)}",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run",
        help="Print what would be done without executing.",
    ),
) -> None:
    """Run pipeline stages (discover → score) for a campaign.

    Review and export are separate explicit actions not included in 'run'.
    """
    try:
        cid = uuid.UUID(campaign_id)
    except ValueError:
        console.print(f"[red]Error: {campaign_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    if from_stage not in STAGES:
        valid = ", ".join(STAGES)
        console.print(f"[red]Error: invalid --from-stage {from_stage!r}. Valid: {valid}[/red]")
        raise typer.Exit(1)

    if to_stage not in STAGES:
        valid = ", ".join(STAGES)
        console.print(f"[red]Error: invalid --to-stage {to_stage!r}. Valid: {valid}[/red]")
        raise typer.Exit(1)

    label = "[dim](dry run)[/dim]" if dry_run else ""
    console.print(f"\n[bold]Running pipeline {from_stage}→{to_stage} for campaign {cid} {label}[/bold]\n")

    try:
        pipeline_summary = run_pipeline(
            cid,
            from_stage=from_stage,
            to_stage=to_stage,
            dry_run=dry_run,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(1)

    _print_pipeline_summary(pipeline_summary)

    if pipeline_summary.total_errors > 0:
        raise typer.Exit(1)


@app.command()
def mark_contacted(
    lead_id: str = typer.Option(
        ..., "--lead-id",
        help="UUID of the lead to mark as contacted.",
    ),
) -> None:
    """Mark a lead as CONTACTED (from QUALIFIED)."""
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        console.print(f"[red]Error: {lead_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        try:
            lead = mark_contacted(session, lid)
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1)

    console.print(f"[green]Lead {lid} marked as CONTACTED.[/green]")


@app.command()
def mark_converted(
    lead_id: str = typer.Option(
        ..., "--lead-id",
        help="UUID of the lead to mark as converted.",
    ),
) -> None:
    """Mark a lead as CONVERTED (from CONTACTED)."""
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        console.print(f"[red]Error: {lead_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        try:
            lead = mark_converted(session, lid)
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1)

    console.print(f"[green]Lead {lid} marked as CONVERTED.[/green]")


@app.command()
def mark_churned(
    lead_id: str = typer.Option(
        ..., "--lead-id",
        help="UUID of the lead to mark as churned.",
    ),
) -> None:
    """Mark a lead as CHURNED (from CONTACTED or CONVERTED)."""
    try:
        lid = uuid.UUID(lead_id)
    except ValueError:
        console.print(f"[red]Error: {lead_id!r} is not a valid UUID[/red]")
        raise typer.Exit(1)

    with get_session() as session:
        try:
            lead = mark_churned(session, lid)
        except ValueError as exc:
            console.print(f"[red]Error: {exc}[/red]")
            raise typer.Exit(1)

    console.print(f"[green]Lead {lid} marked as CHURNED.[/green]")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _print_discovery_summary(summary: object) -> None:
    """Print a Rich table summarising a ``DiscoverySummary``."""
    table = Table(title="Discovery complete", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Queries run", summary.queries_run),           # type: ignore[attr-defined]
        ("Total API results", summary.total_results),   # type: ignore[attr-defined]
        ("Companies created (new)", summary.companies_created),  # type: ignore[attr-defined]
        ("Companies matched", summary.companies_matched),        # type: ignore[attr-defined]
        ("Hits logged (new)", summary.hits_created),             # type: ignore[attr-defined]
        ("Hits skipped (existing)", summary.hits_skipped),       # type: ignore[attr-defined]
        ("Errors", summary.errors),                              # type: ignore[attr-defined]
    ]

    for label, value in rows:
        row_style = "red" if label == "Errors" and value > 0 else ""
        table.add_row(label, str(value), style=row_style)

    console.print(table)

    if summary.error_details:  # type: ignore[attr-defined]
        console.print("\n[red]Errors:[/red]")
        for detail in summary.error_details:  # type: ignore[attr-defined]
            console.print(f"  - {detail}")
    console.print()


def _print_scrape_summary(summary: ScrapeSummary) -> None:
    """Print a Rich table summarising a ``ScrapeSummary``."""
    table = Table(title="Scrape complete", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Hits scraped", summary.hits_scraped),
        ("Hits skipped", summary.hits_skipped),
        ("Hits failed", summary.hits_failed),
        ("Pages saved (new)", summary.pages_saved),
        ("Pages deduplicated", summary.pages_deduplicated),
        ("Errors", summary.errors),
    ]

    for label, value in rows:
        row_style = "red" if label in ("Hits failed", "Errors") and value > 0 else ""
        table.add_row(label, str(value), style=row_style)

    console.print(table)

    if summary.error_details:
        console.print("\n[red]Errors:[/red]")
        for detail in summary.error_details:
            console.print(f"  - {detail}")
    console.print()


def _print_extraction_summary(summary: ExtractionSummary) -> None:
    """Print a Rich table summarising an ``ExtractionSummary``."""
    table = Table(title="Extraction complete", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Hits processed", summary.hits_processed),
        ("Hits with data", summary.hits_with_data),
        ("Hits with zero data", summary.hits_zero_data),
        ("Hits failed", summary.hits_failed),
        ("Hits skipped", summary.hits_skipped),
        ("Contacts created", summary.contacts_created),
        ("Emails created", summary.emails_created),
        ("Phones created", summary.phones_created),
        ("Errors", summary.errors),
    ]

    for label, value in rows:
        row_style = "red" if label in ("Hits failed", "Errors") and value > 0 else ""
        table.add_row(label, str(value), style=row_style)

    console.print(table)

    if summary.error_details:
        console.print("\n[red]Errors:[/red]")
        for detail in summary.error_details:
            console.print(f"  - {detail}")
    console.print()


def _print_verification_summary(summary: VerificationSummary) -> None:
    """Print a Rich table summarising a :class:`VerificationSummary`."""
    table = Table(title="Verification complete", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Emails verified", summary.emails_verified),
        ("Emails valid", summary.emails_valid),
        ("Emails invalid", summary.emails_invalid),
        ("Emails risky", summary.emails_risky),
        ("Phones classified", summary.phones_classified),
        ("Websites checked", summary.websites_checked),
        ("Websites reachable", summary.websites_reachable),
        ("Errors", summary.errors),
    ]

    for label, value in rows:
        row_style = "red" if label == "Errors" and value > 0 else ""
        table.add_row(label, str(value), style=row_style)

    console.print(table)

    if summary.error_details:
        console.print("\n[red]Errors:[/red]")
        for detail in summary.error_details:
            console.print(f"  - {detail}")
    console.print()


def _print_scoring_summary(summary: ScoringRunSummary) -> None:
    """Print a Rich table summarising a :class:`ScoringRunSummary`."""
    table = Table(title="Scoring complete", show_header=True, header_style="bold")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    rows = [
        ("Companies processed", summary.companies_processed),
        ("Leads created", summary.leads_created),
        ("Leads updated", summary.leads_updated),
        ("Leads disqualified", summary.leads_disqualified),
        ("Hot", summary.hot),
        ("Warm", summary.warm),
        ("Cold", summary.cold),
        ("Errors", summary.errors),
    ]

    for label, value in rows:
        row_style = "red" if label == "Errors" and value > 0 else ""
        table.add_row(label, str(value), style=row_style)

    console.print(table)

    if summary.error_details:
        console.print("\n[red]Errors:[/red]")
        for detail in summary.error_details:
            console.print(f"  - {detail}")
    console.print()


def _print_export_summary(summary: ExportSummary) -> None:
    """Print a Rich table summarising an :class:`ExportSummary`."""
    table = Table(title="Export complete", show_header=True, header_style="bold")
    table.add_column("File", style="bold")
    table.add_column("Rows", justify="right")

    table.add_row("Contacts (named)", str(summary.contacts_rows))
    table.add_row("Companies (fallback)", str(summary.companies_rows))
    table.add_row("Leads (full view)", str(summary.leads_rows))

    console.print(table)

    if summary.contacts_file:
        console.print(f"  Contacts:  {summary.contacts_file}")
    if summary.companies_file:
        console.print(f"  Companies: {summary.companies_file}")
    if summary.leads_file:
        console.print(f"  Leads:     {summary.leads_file}")

    if summary.errors > 0:
        console.print(f"\n[red]Errors ({summary.errors}):[/red]")
        for detail in summary.error_details:
            console.print(f"  - {detail}")
    console.print()


def _print_pipeline_summary(summary: PipelineSummary) -> None:
    """Print a Rich summary for a :class:`PipelineSummary`."""
    from rich.panel import Panel

    for stage, ss in summary.stage_summaries.items():
        lines = [
            f"processed={ss.processed}  succeeded={ss.succeeded}  "
            f"failed={ss.failed}  skipped={ss.skipped}",
        ]
        if ss.errors:
            for err in ss.errors:
                lines.append(f"  [red]ERROR: {err}[/red]")
        style = "red" if ss.errors else "green"
        console.print(Panel("\n".join(lines), title=f"Stage: {stage}", style=style, expand=False))

    console.print(
        f"\n[bold]Pipeline complete.[/bold]  "
        f"Total errors: [{'red' if summary.total_errors else 'green'}]"
        f"{summary.total_errors}[/{'red' if summary.total_errors else 'green'}]\n"
    )


if __name__ == "__main__":
    app()

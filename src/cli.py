"""leads — command-line interface for the lead discovery platform.

Each sub-command maps to one pipeline stage.
Run ``leads --help`` or ``leads <command> --help`` for usage.
"""
from __future__ import annotations

import uuid
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from src.db.session import get_session
from src.discovery.runner import run_discovery_for_campaign
from src.models.campaign import Campaign
from src.models.enums import CampaignStatus, GeoMethod
from src.scraper.runner import ScrapeSummary, run_scrape_for_campaign

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
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run ID to process."),
) -> None:
    """Run LLM extraction on scraped pages."""
    console.print("[yellow]extract: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def verify(
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run ID to process."),
) -> None:
    """Validate extracted lead fields (email, phone, URL)."""
    console.print("[yellow]verify: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def score(
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Run ID to process."),
) -> None:
    """Score leads by quality."""
    console.print("[yellow]score: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def review() -> None:
    """Interactive human review of scored leads (approve / reject / skip)."""
    console.print("[yellow]review: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def export(
    output: str = typer.Option("leads.csv", "--output", "-o", help="Output file path."),
    min_score: float = typer.Option(0.0, "--min-score", help="Minimum score to include."),
) -> None:
    """Export approved leads to CSV."""
    console.print("[yellow]export: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def run(
    input: str = typer.Argument(..., help="Path to a newline-delimited file of seed URLs."),
    from_stage: Optional[str] = typer.Option(
        None,
        "--from-stage",
        help="Resume pipeline from a specific stage: scrape|extract|verify|score|review|export",
    ),
) -> None:
    """Run the full pipeline end-to-end."""
    console.print("[yellow]run: not yet implemented[/yellow]")
    raise typer.Exit(1)


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


if __name__ == "__main__":
    app()

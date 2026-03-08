"""leads — command-line interface for the lead discovery platform.

Each sub-command maps to one pipeline stage.
Run ``leads --help`` or ``leads <command> --help`` for usage.
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="leads",
    help="Lead discovery platform.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def discover(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Discovery config file."),
) -> None:
    """Find candidate source URLs and record them in the database."""
    console.print("[yellow]discover: not yet implemented[/yellow]")
    raise typer.Exit(1)


@app.command()
def scrape(
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Resume an existing run."),
    limit: int = typer.Option(0, "--limit", help="Max sources to scrape (0 = unlimited)."),
) -> None:
    """Fetch pages and save raw HTML to data/pages/."""
    console.print("[yellow]scrape: not yet implemented[/yellow]")
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


if __name__ == "__main__":
    app()

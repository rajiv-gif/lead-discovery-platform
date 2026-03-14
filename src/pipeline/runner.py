"""Orchestrate the lead discovery pipeline stages for a campaign."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from src.discovery.runner import run_discovery_for_campaign
from src.extraction.runner import run_extraction_for_campaign
from src.scraper.runner import run_scrape_for_campaign
from src.scoring.runner import run_scoring_for_campaign
from src.verification.runner import run_verification_for_campaign

log = logging.getLogger(__name__)

# Stages in pipeline order (review and export are NOT automated pipeline stages)
STAGES = ["discover", "scrape", "extract", "verify", "score"]


@dataclass
class StageSummary:
    stage: str
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class PipelineSummary:
    campaign_id: str
    stages_run: list[str]
    stage_summaries: dict[str, StageSummary]
    total_errors: int = 0


def _summary_from_scrape(scrape_summary, stage: str) -> StageSummary:
    from src.scraper.runner import ScrapeSummary
    ss = StageSummary(stage=stage)
    ss.processed = scrape_summary.hits_scraped + scrape_summary.hits_failed + scrape_summary.hits_skipped
    ss.succeeded = scrape_summary.hits_scraped
    ss.failed = scrape_summary.hits_failed
    ss.skipped = scrape_summary.hits_skipped
    ss.errors = list(scrape_summary.error_details)
    return ss


def _summary_from_extraction(extract_summary, stage: str) -> StageSummary:
    ss = StageSummary(stage=stage)
    ss.processed = extract_summary.hits_processed
    ss.succeeded = extract_summary.hits_with_data
    ss.failed = extract_summary.hits_failed
    ss.skipped = extract_summary.hits_skipped
    ss.errors = list(extract_summary.error_details)
    return ss


def _summary_from_verification(verify_summary, stage: str) -> StageSummary:
    ss = StageSummary(stage=stage)
    ss.processed = verify_summary.emails_verified + verify_summary.phones_classified
    ss.succeeded = verify_summary.emails_valid + verify_summary.phones_classified
    ss.failed = verify_summary.errors
    ss.skipped = 0
    ss.errors = list(verify_summary.error_details)
    return ss


def _summary_from_scoring(scoring_summary, stage: str) -> StageSummary:
    ss = StageSummary(stage=stage)
    ss.processed = scoring_summary.companies_processed
    ss.succeeded = scoring_summary.leads_created + scoring_summary.leads_updated
    ss.failed = scoring_summary.errors
    ss.skipped = 0
    ss.errors = list(scoring_summary.error_details)
    return ss


def _summary_from_discovery(discovery_summary, stage: str) -> StageSummary:
    ss = StageSummary(stage=stage)
    ss.processed = discovery_summary.total_results
    ss.succeeded = discovery_summary.companies_created + discovery_summary.companies_matched
    ss.failed = discovery_summary.errors
    ss.skipped = discovery_summary.hits_skipped
    ss.errors = list(discovery_summary.error_details)
    return ss


def run_pipeline(
    campaign_id: uuid.UUID,
    from_stage: str = "discover",
    to_stage: str = "score",
    dry_run: bool = False,
) -> PipelineSummary:
    """Run pipeline stages for a campaign from *from_stage* through *to_stage*.

    Args:
        campaign_id: UUID of the campaign to process.
        from_stage: First stage to run (inclusive). Must be in STAGES.
        to_stage: Last stage to run (inclusive). Must be in STAGES.
        dry_run: If True, print what would be done but skip actual execution.

    Returns:
        PipelineSummary with per-stage results.

    Raises:
        ValueError: If from_stage or to_stage are invalid, or from_stage > to_stage.
    """
    if from_stage not in STAGES:
        raise ValueError(
            f"Invalid from_stage {from_stage!r}. Valid stages: {STAGES}"
        )
    if to_stage not in STAGES:
        raise ValueError(
            f"Invalid to_stage {to_stage!r}. Valid stages: {STAGES}"
        )

    from_idx = STAGES.index(from_stage)
    to_idx = STAGES.index(to_stage)

    if from_idx > to_idx:
        raise ValueError(
            f"from_stage {from_stage!r} (index {from_idx}) must come before "
            f"to_stage {to_stage!r} (index {to_idx})"
        )

    stages_to_run = STAGES[from_idx: to_idx + 1]

    summary = PipelineSummary(
        campaign_id=str(campaign_id),
        stages_run=stages_to_run,
        stage_summaries={},
    )

    # Track verify→score in-process website results
    website_results: Optional[dict] = None
    run_both_verify_and_score = "verify" in stages_to_run and "score" in stages_to_run

    for stage in stages_to_run:
        if dry_run:
            log.info("dry_run: would run stage %r for campaign %s", stage, campaign_id)
            ss = StageSummary(stage=stage)
            ss.skipped = 1
            summary.stage_summaries[stage] = ss
            continue

        try:
            if stage == "discover":
                result = run_discovery_for_campaign(campaign_id)
                ss = _summary_from_discovery(result, stage)

            elif stage == "scrape":
                result = run_scrape_for_campaign(campaign_id)
                ss = _summary_from_scrape(result, stage)

            elif stage == "extract":
                result = run_extraction_for_campaign(campaign_id)
                ss = _summary_from_extraction(result, stage)

            elif stage == "verify":
                verify_summary, wr = run_verification_for_campaign(campaign_id)
                if run_both_verify_and_score:
                    website_results = wr
                ss = _summary_from_verification(verify_summary, stage)

            elif stage == "score":
                score_result = run_scoring_for_campaign(
                    campaign_id,
                    website_results=website_results,
                )
                ss = _summary_from_scoring(score_result, stage)

            else:
                ss = StageSummary(stage=stage)
                ss.errors.append(f"Unknown stage: {stage!r}")

        except NotImplementedError as exc:
            log.warning("Stage %r not yet implemented: %s", stage, exc)
            ss = StageSummary(stage=stage)
            ss.errors.append(f"Not implemented: {exc}")

        except Exception as exc:
            log.error("Stage %r failed: %s", stage, exc, exc_info=True)
            ss = StageSummary(stage=stage)
            ss.errors.append(str(exc))

        summary.stage_summaries[stage] = ss
        summary.total_errors += len(ss.errors)

    return summary

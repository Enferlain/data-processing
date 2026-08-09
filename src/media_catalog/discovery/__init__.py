from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from media_catalog.database import CatalogDatabase
from media_catalog.discovery.candidates import CandidateGenerator
from media_catalog.discovery.posts import PostMatchManager
from media_catalog.discovery.queries import DiscoveryQueries
from media_catalog.discovery.review import MatchReviewService
from media_catalog.discovery.scan import LinkOccurrenceScanner
from media_catalog.discovery.support import digest as _digest
from media_catalog.discovery.support import now as _now
from media_catalog.links import (
    CANONICALIZER_VERSION,
    EXTRACTOR_VERSION,
    RECOGNIZER_VERSION,
    SCORING_VERSION,
    recognize_url,
)
from media_catalog.records import LinkOccurrence
from media_catalog.writer import CatalogWriter


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    run_id: int
    status: str
    versions: dict[str, str]
    counts: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class DiscoveryService:
    def __init__(self, database: CatalogDatabase) -> None:
        self.database = database
        self.connection = database.connection
        self.writer = CatalogWriter(database)
        self._scanner = LinkOccurrenceScanner(self.connection)
        self._candidate_generator = CandidateGenerator(self.connection)
        self._queries = DiscoveryQueries(self.connection)
        self._review_service = MatchReviewService(database)
        self._post_matches = PostMatchManager(database)

    def discover(self) -> DiscoveryResult:
        now = _now()
        counts = {
            key: 0
            for key in ("scanned", "observed", "recognized", "unresolved", "existing", "failed")
        }
        versions = {
            "extractor": EXTRACTOR_VERSION,
            "canonicalizer": CANONICALIZER_VERSION,
            "recognizer": RECOGNIZER_VERSION,
            "scoring": SCORING_VERSION,
        }
        with self.database.transaction():
            run_id = self.writer.begin_discovery(
                extractor_version=EXTRACTOR_VERSION,
                canonicalizer_version=CANONICALIZER_VERSION,
                recognizer_version=RECOGNIZER_VERSION,
                scoring_version=SCORING_VERSION,
                started_at=now,
            )
            for occurrence in self._occurrences(counts):
                counts["scanned"] += 1
                try:
                    result = recognize_url(occurrence.original_url)
                    digest = _digest(
                        occurrence.subject_kind,
                        occurrence.subject_id,
                        occurrence.account_snapshot_id,
                        occurrence.raw_observation_id,
                        occurrence.source_context,
                        occurrence.json_path or "",
                        occurrence.original_url,
                        occurrence.observed_at,
                    )
                    stored, reference_id = self.writer.store_link_observation(
                        run_id,
                        occurrence,
                        canonical_url=result.canonical.canonical_url,
                        canonicalization_version=CANONICALIZER_VERSION,
                        resolution_state=result.canonical.state,
                        resolution_reason=result.canonical.reason,
                        extractor_version=EXTRACTOR_VERSION,
                        occurrence_digest=digest,
                        original_query=result.canonical.original_query,
                        original_fragment=result.canonical.original_fragment,
                        reference=result.reference,
                    )
                    counts["existing" if stored.outcome == "existing" else "observed"] += 1
                    counts["recognized" if reference_id is not None else "unresolved"] += 1
                    if reference_id is not None:
                        self._generate_candidate(occurrence, stored.id, reference_id, now)
                except (TypeError, ValueError, json.JSONDecodeError):
                    counts["failed"] += 1
            self.connection.execute(
                """DELETE FROM external_link_references
                   WHERE NOT EXISTS (
                       SELECT 1 FROM link_observations lo
                       WHERE lo.external_link_id = external_link_references.external_link_id
                   )"""
            )
            self.connection.execute(
                """DELETE FROM external_links
                   WHERE NOT EXISTS (
                       SELECT 1 FROM link_observations lo
                       WHERE lo.external_link_id = external_links.external_link_id
                   ) AND NOT EXISTS (
                       SELECT 1 FROM external_link_references elr
                       WHERE elr.external_link_id = external_links.external_link_id
                   )"""
            )
            self.writer.finish_discovery(
                run_id, status="complete", finished_at=_now(), counts=counts
            )
        return DiscoveryResult(run_id, "complete", versions, counts)

    def _occurrences(self, counts: dict[str, int]) -> list[LinkOccurrence]:
        return self._scanner.scan(counts)

    def _generate_candidate(
        self, occurrence: LinkOccurrence, observation_id: int, reference_id: int, now: str
    ) -> None:
        self._candidate_generator.generate(
            occurrence,
            observation_id,
            reference_id,
            now,
            extractor_version=EXTRACTOR_VERSION,
            scoring_version=SCORING_VERSION,
        )

    def links(self, **filters: object) -> dict[str, object]:
        return self._queries.links(**filters)

    def candidates(self, *, kind: str | None = None, state: str | None = None) -> dict[str, object]:
        return self._queries.candidates(kind=kind, state=state)

    def candidate(self, match_ref: str) -> dict[str, object]:
        return self._queries.candidate(match_ref)

    def review(
        self,
        match_ref: str,
        decision: str,
        *,
        note: str | None = None,
        expected_generation: int | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        return self._review_service.review(
            match_ref,
            decision,
            note=note,
            expected_generation=expected_generation,
            expected_revision=expected_revision,
        )

    def add_characteristic(
        self,
        match_ref: str,
        characteristic: str,
        *,
        direction: str = "none",
        source_label: str = "manual",
    ) -> None:
        self._post_matches.add_characteristic(
            match_ref,
            characteristic,
            direction=direction,
            source_label=source_label,
        )

    def create_post_candidate(
        self,
        subject_post_id: int,
        target_post_id: int,
        relation: str,
        *,
        explanation: str,
        strength: str = "moderate",
    ) -> str:
        return self._post_matches.create_post_candidate(
            subject_post_id,
            target_post_id,
            relation,
            explanation=explanation,
            strength=strength,
            scoring_version=SCORING_VERSION,
        )

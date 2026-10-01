from __future__ import annotations

from media_catalog.database import CatalogDatabase
from media_catalog.persistence.acquisition import AcquisitionWrites
from media_catalog.persistence.catalog import CatalogWrites
from media_catalog.persistence.discovery import DiscoveryWrites
from media_catalog.persistence.library import LibraryWrites
from media_catalog.persistence.lookup import LookupWrites
from media_catalog.persistence.metadata import MetadataWrites
from media_catalog.persistence.remote import RemoteWrites
from media_catalog.persistence.storage import StorageWrites
from media_catalog.persistence.support import (
    WriteResult,
    platform_id,
)
from media_catalog.records import (
    AccountRecord,
    AcquisitionAttemptRecord,
    AcquisitionPartialRecord,
    AcquisitionPlanItemRecord,
    AcquisitionPlanRecord,
    AcquisitionQuarantineRecord,
    AcquisitionRunItemRecord,
    AcquisitionRunRecord,
    AcquisitionVerificationRecord,
    AdoptionAttemptRecord,
    AdoptionItemRecord,
    AdoptionRunRecord,
    AssetFingerprintRecord,
    AssetLocationRecord,
    AssetRecord,
    AttributionRecord,
    CandidateLookupCheckpointRecord,
    CandidateLookupRequestRecord,
    CandidateLookupResultRecord,
    CandidateLookupRunRecord,
    LibraryExpansionExecutionRecord,
    LibraryExpansionPlanRecord,
    LibraryExpansionPostRecord,
    LibraryExpansionProbeRecord,
    LinkOccurrence,
    ManagedRootRecord,
    MediaOccurrenceRecord,
    OccurrenceSourceRecord,
    PlatformReferenceRecord,
    PostExternalReferenceRecord,
    PostFlagObservationRecord,
    PostMetadataObservationRecord,
    PostPoolObservationRecord,
    PostRecord,
    RawRecord,
    RemoteCheckpointRecord,
    RemoteRequestRecord,
    RemoteRunRecord,
    TagAliasObservationRecord,
    TagObservationRecord,
)


class CatalogWriter:
    def __init__(self, database: CatalogDatabase) -> None:
        self.database = database
        self.connection = database.connection
        self._storage = StorageWrites(database)
        self._acquisition = AcquisitionWrites(database)
        self._lookup = LookupWrites(database)
        self._library = LibraryWrites(database)
        self._remote = RemoteWrites(database)
        self._metadata = MetadataWrites(database)
        self._discovery = DiscoveryWrites(database)
        self._catalog = CatalogWrites(database)

    def platform_id(self, platform: str) -> int:
        return platform_id(self.connection, platform)

    def begin_discovery(
        self,
        *,
        extractor_version: str,
        canonicalizer_version: str,
        recognizer_version: str,
        scoring_version: str,
        started_at: str,
    ) -> int:
        return self._discovery.begin_discovery(
            extractor_version=extractor_version,
            canonicalizer_version=canonicalizer_version,
            recognizer_version=recognizer_version,
            scoring_version=scoring_version,
            started_at=started_at,
        )

    def finish_discovery(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        counts: dict[str, int],
        diagnostic: str | None = None,
    ) -> None:
        self._discovery.finish_discovery(
            run_id,
            status=status,
            finished_at=finished_at,
            counts=counts,
            diagnostic=diagnostic,
        )

    def store_link_observation(
        self,
        run_id: int,
        occurrence: LinkOccurrence,
        *,
        canonical_url: str,
        canonicalization_version: str,
        resolution_state: str,
        resolution_reason: str | None,
        extractor_version: str,
        occurrence_digest: str,
        original_query: str,
        original_fragment: str,
        reference: PlatformReferenceRecord | None,
    ) -> tuple[WriteResult, int | None]:
        return self._discovery.store_link_observation(
            run_id,
            occurrence,
            canonical_url=canonical_url,
            canonicalization_version=canonicalization_version,
            resolution_state=resolution_state,
            resolution_reason=resolution_reason,
            extractor_version=extractor_version,
            occurrence_digest=occurrence_digest,
            original_query=original_query,
            original_fragment=original_fragment,
            reference=reference,
        )

    def store_raw(
        self,
        record: RawRecord,
        *,
        import_run_id: int | None = None,
        remote_run_id: int | None = None,
        remote_request_id: int | None = None,
    ) -> int:
        return self._remote.store_raw(
            record,
            import_run_id=import_run_id,
            remote_run_id=remote_run_id,
            remote_request_id=remote_request_id,
        )

    def begin_remote_run(self, record: RemoteRunRecord) -> int:
        return self._remote.begin_remote_run(record)

    def finish_remote_run(
        self,
        remote_run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        record_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._remote.finish_remote_run(
            remote_run_id,
            status=status,
            outcome=outcome,
            request_count=request_count,
            page_count=page_count,
            record_count=record_count,
            finished_at=finished_at,
            budget_boundary=budget_boundary,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )

    def record_remote_request(self, record: RemoteRequestRecord) -> int:
        return self._remote.record_remote_request(record)

    def save_remote_checkpoint(self, record: RemoteCheckpointRecord) -> int:
        return self._remote.save_remote_checkpoint(record)

    def upsert_tag(
        self,
        post_id: int,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_tag(post_id, record, raw_observation_id=raw_observation_id)

    def upsert_tag_record(
        self,
        record: TagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        """Persist a standalone provider tag observation without inventing a post link."""
        return self._metadata.upsert_tag_record(record, raw_observation_id=raw_observation_id)

    def upsert_tag_alias(
        self,
        record: TagAliasObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_tag_alias(record, raw_observation_id=raw_observation_id)

    def record_post_metadata(
        self,
        post_id: int,
        record: PostMetadataObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_metadata(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def record_post_pool(
        self,
        post_id: int,
        record: PostPoolObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_pool(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def record_post_flag(
        self,
        post_id: int,
        record: PostFlagObservationRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.record_post_flag(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def upsert_attribution(
        self,
        record: AttributionRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._metadata.upsert_attribution(record, raw_observation_id=raw_observation_id)

    def add_post_external_reference(
        self,
        post_id: int,
        record: PostExternalReferenceRecord,
        *,
        raw_observation_id: int,
    ) -> int:
        return self._metadata.add_post_external_reference(
            post_id, record, raw_observation_id=raw_observation_id
        )

    def add_account_external_link(
        self,
        account_id: int,
        url: str,
        source_context: str,
        observed_at: str,
        *,
        raw_observation_id: int,
    ) -> int:
        return self._metadata.add_account_external_link(
            account_id,
            url,
            source_context,
            observed_at,
            raw_observation_id=raw_observation_id,
        )

    def upsert_account(
        self, record: AccountRecord, *, raw_observation_id: int | None = None
    ) -> WriteResult:
        return self._catalog.upsert_account(record, raw_observation_id=raw_observation_id)

    def upsert_post(
        self, record: PostRecord, *, raw_observation_id: int | None = None
    ) -> WriteResult:
        return self._catalog.upsert_post(record, raw_observation_id=raw_observation_id)

    def add_participant(
        self, post_id: int, account_id: int, role: str, *, raw_observation_id: int | None = None
    ) -> None:
        self._catalog.add_participant(
            post_id, account_id, role, raw_observation_id=raw_observation_id
        )

    def add_observation(
        self,
        post_id: int,
        event_type: str,
        source_kind: str,
        source_event_key: str,
        observed_at: str,
        *,
        import_run_id: int | None = None,
        raw_observation_id: int | None = None,
        collection_data: str | None = None,
    ) -> WriteResult:
        return self._catalog.add_observation(
            post_id,
            event_type,
            source_kind,
            source_event_key,
            observed_at,
            import_run_id=import_run_id,
            raw_observation_id=raw_observation_id,
            collection_data=collection_data,
        )

    def add_relation(
        self,
        source_post_id: int,
        target_post_id: int,
        relation_type: str,
        *,
        raw_observation_id: int | None = None,
    ) -> None:
        self._catalog.add_relation(
            source_post_id, target_post_id, relation_type, raw_observation_id=raw_observation_id
        )

    def upsert_media(
        self,
        post_id: int,
        record: MediaOccurrenceRecord,
        *,
        raw_observation_id: int | None = None,
    ) -> WriteResult:
        return self._catalog.upsert_media(post_id, record, raw_observation_id=raw_observation_id)

    def link_asset(
        self, occurrence_id: int, record: AssetRecord, *, relationship: str = "reference"
    ) -> int:
        return self._catalog.link_asset(occurrence_id, record, relationship=relationship)

    def register_managed_root(self, record: ManagedRootRecord) -> int:
        """Insert or retrieve a stable source/managed root identity."""
        return self._storage.register_managed_root(record)

    # Compatibility spelling used by callers that treat roots as an upsert.
    upsert_managed_root = register_managed_root

    def add_asset_location(self, record: AssetLocationRecord) -> int:
        return self._storage.add_asset_location(record)

    def add_occurrence_source(self, record: OccurrenceSourceRecord) -> int:
        return self._storage.add_occurrence_source(record)

    def add_asset_fingerprint(self, record: AssetFingerprintRecord) -> int:
        return self._storage.add_asset_fingerprint(record)

    def begin_adoption_run(self, record: AdoptionRunRecord) -> int:
        return self._storage.begin_adoption_run(record)

    def finish_adoption_run(
        self,
        run_id: int,
        *,
        status: str,
        finished_at: str,
        completed_count: int | None = None,
        failed_count: int | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._storage.finish_adoption_run(
            run_id,
            status=status,
            finished_at=finished_at,
            completed_count=completed_count,
            failed_count=failed_count,
            diagnostic=diagnostic,
        )

    def record_adoption_item(self, record: AdoptionItemRecord) -> int:
        return self._storage.record_adoption_item(record)

    def record_adoption_attempt(self, record: AdoptionAttemptRecord) -> int:
        return self._storage.record_adoption_attempt(record)

    def adoption_items(self, run_id: int | None = None) -> list[dict[str, object]]:
        if run_id is None:
            rows = self.connection.execute("SELECT * FROM adoption_items ORDER BY adoption_item_id")
        else:
            rows = self.connection.execute(
                "SELECT * FROM adoption_items WHERE adoption_run_id = ? ORDER BY adoption_item_id",
                (run_id,),
            )
        return [dict(row) for row in rows]

    def create_acquisition_plan(self, record: AcquisitionPlanRecord) -> int:
        return self._acquisition.create_acquisition_plan(record)

    def add_acquisition_plan_item(self, record: AcquisitionPlanItemRecord) -> int:
        return self._acquisition.add_acquisition_plan_item(record)

    def begin_acquisition_run(self, record: AcquisitionRunRecord) -> int:
        return self._acquisition.begin_acquisition_run(record)

    def finish_acquisition_run(
        self,
        acquisition_run_id: int,
        *,
        status: str,
        outcome: str,
        completed_count: int,
        failed_count: int,
        deferred_count: int,
        received_bytes: int,
        quarantined_bytes: int,
        finished_at: str,
        diagnostic: str | None = None,
    ) -> None:
        self._acquisition.finish_acquisition_run(
            acquisition_run_id,
            status=status,
            outcome=outcome,
            completed_count=completed_count,
            failed_count=failed_count,
            deferred_count=deferred_count,
            received_bytes=received_bytes,
            quarantined_bytes=quarantined_bytes,
            finished_at=finished_at,
            diagnostic=diagnostic,
        )

    def record_acquisition_run_item(self, record: AcquisitionRunItemRecord) -> int:
        return self._acquisition.record_acquisition_run_item(record)

    def record_acquisition_attempt(self, record: AcquisitionAttemptRecord) -> int:
        return self._acquisition.record_acquisition_attempt(record)

    def save_acquisition_partial(self, record: AcquisitionPartialRecord) -> int:
        return self._acquisition.save_acquisition_partial(record)

    def record_acquisition_verification(self, record: AcquisitionVerificationRecord) -> int:
        return self._acquisition.record_acquisition_verification(record)

    def record_acquisition_quarantine(self, record: AcquisitionQuarantineRecord) -> int:
        return self._acquisition.record_acquisition_quarantine(record)

    def begin_candidate_lookup(self, record: CandidateLookupRunRecord) -> int:
        return self._lookup.begin_candidate_lookup(record)

    def finish_candidate_lookup(
        self,
        run_id: int,
        *,
        status: str,
        outcome: str,
        request_count: int,
        page_count: int,
        result_count: int,
        finished_at: str,
        budget_boundary: str | None = None,
        retry_after: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        self._lookup.finish_candidate_lookup(
            run_id,
            status=status,
            outcome=outcome,
            request_count=request_count,
            page_count=page_count,
            result_count=result_count,
            finished_at=finished_at,
            budget_boundary=budget_boundary,
            retry_after=retry_after,
            diagnostic=diagnostic,
        )

    def record_candidate_lookup_request(self, record: CandidateLookupRequestRecord) -> int:
        return self._lookup.record_candidate_lookup_request(record)

    def save_candidate_lookup_checkpoint(self, record: CandidateLookupCheckpointRecord) -> int:
        return self._lookup.save_candidate_lookup_checkpoint(record)

    def record_candidate_lookup_result(self, record: CandidateLookupResultRecord) -> int:
        return self._lookup.record_candidate_lookup_result(record)

    def record_library_expansion_plan(self, record: LibraryExpansionPlanRecord) -> int:
        return self._library.record_library_expansion_plan(record)

    def record_library_expansion_probe(self, record: LibraryExpansionProbeRecord) -> int:
        return self._library.record_library_expansion_probe(record)

    def record_library_expansion_execution(self, record: LibraryExpansionExecutionRecord) -> int:
        return self._library.record_library_expansion_execution(record)

    def record_library_expansion_post(self, record: LibraryExpansionPostRecord) -> int:
        return self._library.record_library_expansion_post(record)

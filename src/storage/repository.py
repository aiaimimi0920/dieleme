from __future__ import annotations

import os
from datetime import datetime

from .repository_context import DatabaseSettings, _env_flag
from .repository_core import RepositoryCoreMixin
from .repository_flat_payload import RepositoryFlatPayloadMixin
from .repository_flat_query import RepositoryFlatQueryMixin
from .repository_geo import RepositoryGeoMixin
from .repository_collection import RepositoryCollectionMixin
from .repository_readiness import RepositoryReadinessMixin
from .repository_task_events import RepositoryTaskEventsMixin
from .repository_search import RepositorySearchMixin
from .repository_seed_scan_jobs import RepositorySeedScanJobsMixin
from .repository_seed_scan_pages import RepositorySeedScanPagesMixin
from .repository_seed_items import RepositorySeedItemsMixin
from .repository_detail_claim import RepositoryDetailClaimMixin
from .repository_detail_analysis import RepositoryDetailAnalysisMixin
from .repository_observer_regions import RepositoryObserverRegionsMixin
from .repository_observer_items import RepositoryObserverItemsMixin
from .repository_manual_review import RepositoryManualReviewMixin


class PropertyRepository(
    RepositoryCoreMixin,
    RepositoryFlatPayloadMixin,
    RepositoryFlatQueryMixin,
    RepositoryGeoMixin,
    RepositoryCollectionMixin,
    RepositoryReadinessMixin,
    RepositoryTaskEventsMixin,
    RepositorySearchMixin,
    RepositorySeedScanJobsMixin,
    RepositorySeedScanPagesMixin,
    RepositorySeedItemsMixin,
    RepositoryDetailClaimMixin,
    RepositoryDetailAnalysisMixin,
    RepositoryObserverRegionsMixin,
    RepositoryObserverItemsMixin,
    RepositoryManualReviewMixin,
):
    """Facade preserving the repository API across responsibility mixins."""


def create_repository_from_env() -> PropertyRepository:
    settings = DatabaseSettings(
        url=os.environ.get("FAPAI_DB_URL", "").strip(),
        echo=_env_flag("FAPAI_DB_ECHO", False),
        enable_postgis=_env_flag("FAPAI_DB_ENABLE_POSTGIS", False),
        auto_create=_env_flag("FAPAI_DB_AUTO_CREATE", True),
        enabled=_env_flag("FAPAI_DB_ENABLED", True),
    )
    return PropertyRepository(settings=settings)


__all__ = ["DatabaseSettings", "PropertyRepository", "create_repository_from_env"]

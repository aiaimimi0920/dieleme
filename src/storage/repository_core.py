from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositoryCoreMixin:
    def __init__(self, settings: DatabaseSettings):
        self.settings = settings
        self._engine: Engine | None = None
        self._Session: sessionmaker[Session] | None = None
        self._initialized = False

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and self.settings.url)

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            if not self.enabled:
                raise RuntimeError("database repository is disabled")
            self._engine = create_engine(self.settings.url, echo=self.settings.echo, future=True)
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._Session is None:
            self._Session = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)
        return self._Session

    def initialize(self) -> None:
        if not self.enabled or self._initialized:
            return
        if self.settings.auto_create:
            Base.metadata.create_all(self.engine)
        if self.settings.enable_postgis and self.engine.dialect.name == "postgresql":
            self._ensure_postgis()
        self._initialized = True

    def _ensure_postgis(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.execute(
                text(
                    """
                    ALTER TABLE property_listing
                    ADD COLUMN IF NOT EXISTS geom geography(Point, 4326)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_property_listing_geom
                    ON property_listing
                    USING GIST (geom)
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE property_listing
                    SET geom = CASE
                        WHEN longitude IS NOT NULL AND latitude IS NOT NULL
                        THEN ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
                        ELSE NULL
                    END
                    WHERE geom IS NULL
                    """
                )
            )

    def _apply_postgis_point(self, session: Session, item_id: str, latitude: Any, longitude: Any) -> None:
        if self.engine.dialect.name != "postgresql":
            return
        if latitude in (None, "") or longitude in (None, ""):
            session.execute(text("UPDATE property_listing SET geom = NULL WHERE item_id = :item_id"), {"item_id": item_id})
            return
        session.execute(
            text(
                """
                UPDATE property_listing
                SET geom = ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography
                WHERE item_id = :item_id
                """
            ),
            {"item_id": item_id, "latitude": float(latitude), "longitude": float(longitude)},
        )

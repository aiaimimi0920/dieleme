from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositoryGeoMixin:
    def yield_coordinate_rows(self, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    PropertyListing.business_area,
                    PropertyListing.community_name,
                    PropertyListing.latitude,
                    PropertyListing.longitude,
                )
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.latitude.is_not(None),
                    PropertyListing.longitude.is_not(None),
                )
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for city, district, business_area, community_name, latitude, longitude in stream:
                yield {
                    "city": city,
                    "district": district,
                    "business_area": business_area,
                    "community_name": community_name,
                    "latitude": float(latitude) if latitude is not None else None,
                    "longitude": float(longitude) if longitude is not None else None,
                }

    def build_coordinate_centroids(self) -> Dict[str, tuple[float, float]]:
        if not self.enabled:
            return {}
        self.initialize()

        def _non_empty(column):
            return and_(column.is_not(None), column != "")

        base_filters = (
            PropertyListing.is_deleted.is_(False),
            PropertyListing.latitude.is_not(None),
            PropertyListing.longitude.is_not(None),
            PropertyListing.latitude >= 3.0,
            PropertyListing.latitude <= 54.5,
            PropertyListing.longitude >= 73.0,
            PropertyListing.longitude <= 136.0,
        )

        centroids: Dict[str, tuple[float, float]] = {}
        with self.session_factory() as session:
            community_stmt = (
                select(
                    PropertyListing.community_name,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(*base_filters, _non_empty(PropertyListing.community_name))
                .group_by(PropertyListing.community_name)
            )
            for community_name, lat_avg, lon_avg in session.execute(community_stmt):
                centroids[f"community::{community_name}"] = (round(float(lat_avg), 6), round(float(lon_avg), 6))

            business_stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    PropertyListing.business_area,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(
                    *base_filters,
                    _non_empty(PropertyListing.city),
                    _non_empty(PropertyListing.district),
                    _non_empty(PropertyListing.business_area),
                )
                .group_by(PropertyListing.city, PropertyListing.district, PropertyListing.business_area)
            )
            for city, district, business_area, lat_avg, lon_avg in session.execute(business_stmt):
                centroids[f"business::{city}::{district}::{business_area}"] = (
                    round(float(lat_avg), 6),
                    round(float(lon_avg), 6),
                )

            district_stmt = (
                select(
                    PropertyListing.city,
                    PropertyListing.district,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(
                    *base_filters,
                    _non_empty(PropertyListing.city),
                    _non_empty(PropertyListing.district),
                )
                .group_by(PropertyListing.city, PropertyListing.district)
            )
            for city, district, lat_avg, lon_avg in session.execute(district_stmt):
                centroids[f"district::{city}::{district}"] = (
                    round(float(lat_avg), 6),
                    round(float(lon_avg), 6),
                )

            city_stmt = (
                select(
                    PropertyListing.city,
                    func.avg(PropertyListing.latitude),
                    func.avg(PropertyListing.longitude),
                )
                .where(*base_filters, _non_empty(PropertyListing.city))
                .group_by(PropertyListing.city)
            )
            for city, lat_avg, lon_avg in session.execute(city_stmt):
                centroids[f"city::{city}"] = (round(float(lat_avg), 6), round(float(lon_avg), 6))

        return centroids

"""Loading road geometries from an ESRI Shapefile."""
from __future__ import annotations

from pathlib import Path

import geopandas as gpd


class RoadDataError(RuntimeError):
    """Raised when the road source cannot be loaded or validated."""


class RoadDataProvider:
    """Loads and validates road geometries from a Shapefile."""

    def __init__(self, shp_path: str | Path):
        self.shp_path = Path(shp_path)

    def load(self) -> gpd.GeoDataFrame:
        """Read the shapefile and return a validated GeoDataFrame.

        Raises :class:`RoadDataError` for a missing file, missing sidecar files,
        missing CRS or an empty dataset. No CRS is ever guessed.
        """
        if not self.shp_path.exists():
            raise RoadDataError(
                f"Road shapefile not found: {self.shp_path}. "
                "Provide a valid ESRI Shapefile (.shp/.shx/.dbf/.prj/.cpg)."
            )

        self._ensure_sidecar_files()

        try:
            gdf = gpd.read_file(self.shp_path)
        except Exception as exc:  # pragma: no cover - depends on the OGR driver
            raise RoadDataError(f"Failed to read shapefile {self.shp_path}: {exc}") from exc

        if gdf.empty:
            raise RoadDataError(f"Shapefile {self.shp_path} contains no geometries.")

        if gdf.crs is None:
            raise RoadDataError(
                f"Shapefile {self.shp_path} has no CRS. "
                "A valid .prj file is required; refusing to guess the CRS."
            )

        # Drop null/empty geometries.
        gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()
        if gdf.empty:
            raise RoadDataError(
                f"Shapefile {self.shp_path} contains no valid road geometries."
            )
        return gdf

    def _ensure_sidecar_files(self) -> None:
        base = self.shp_path.with_suffix("")
        for ext in (".shp", ".shx", ".dbf", ".prj"):
            candidate = Path(f"{base}{ext}")
            if not candidate.exists():
                raise RoadDataError(
                    f"Missing sidecar file {candidate.name} for shapefile {self.shp_path.name}."
                )

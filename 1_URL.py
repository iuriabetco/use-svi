# ==========================================================
# 1_URL.py — URL generation and metadata logging (portable)
# ==========================================================
# - Works with relative paths (repo-based)
# - Accepts any input shapefile
# - Uses an automatically estimated metric CRS (UTM) for distance-based sampling
# - Deletes existing output CSV and recreates it
# - Writes to CSV after EACH generated URL (crash-safe)
# ==========================================================

import csv
import sys
import argparse
from pathlib import Path
from typing import Iterable, Tuple, List

import geopandas as gpd
from geopy.distance import geodesic


# --------------------------
# Path helpers (portable)
# --------------------------
def get_base_dir() -> Path:
    """
    Returns the folder where this script is located.
    If __file__ is not defined (e.g., running in interactive console),
    it falls back to the current working directory.
    """
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


# --------------------------
# URL + geometry helpers
# --------------------------
def generate_image_url(lat: float, lon: float, angle: int) -> str:
    return (
        "https://www.google.com/maps/@?api=1&map_action=pano"
        f"&viewpoint={lat},{lon}&heading={angle}"
    )


def interpolate_points(line, distance_m: float):
    """
    Interpolates points along a LineString in a metric CRS.
    distance_m is in meters.
    """
    if line.length == 0:
        return []

    total_length = float(line.length)
    num_segments = int(total_length // float(distance_m))

    points = []
    for i in range(num_segments + 1):
        points.append(line.interpolate(i * float(distance_m)))
    return points


def point_is_near(lat: float, lon: float, captured_coords: List[Tuple[float, float]], threshold_m: float) -> bool:
    """
    Enforces minimum spacing using geodesic distance (meters) in WGS84.
    """
    new_point = (lat, lon)
    for existing in captured_coords:
        if geodesic(existing, new_point).meters < threshold_m:
            return True
    return False


def make_key(lat: float, lon: float, angle: int) -> Tuple[float, float, int]:
    """
    Key to avoid duplicates, rounding to reduce floating point noise.
    """
    return (round(float(lat), 7), round(float(lon), 7), int(angle))


def iter_lines(geometry) -> Iterable:
    """
    Yields LineString geometries from LineString/MultiLineString.
    """
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "LineString":
        return [geometry]
    if geometry.geom_type == "MultiLineString":
        return list(geometry.geoms)
    return []


# --------------------------
# Main
# --------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Sample a road network, generate Google Street View URLs, and save a CSV (flush after each URL)."
    )

    base_dir = get_base_dir()
    roads_dir_default = base_dir / "roads"
    outputs_dir_default = base_dir / "outputs"

    parser.add_argument(
        "--roads",
        type=str,
        default=str(roads_dir_default / "roads_lisbon.shp"),
        help="Path to the input road network shapefile (.shp). Default: roads/roads_lisbon.shp",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=str(outputs_dir_default / "streetview_urls.csv"),
        help="Output CSV path. Default: outputs/streetview_urls.csv",
    )
    parser.add_argument(
        "--distance",
        type=float,
        default=30.0,
        help="Sampling distance in meters. Default: 30",
    )
    parser.add_argument(
        "--angles",
        type=str,
        default="0,90,180,270",
        help="Comma-separated headings. Default: 0,90,180,270",
    )
    parser.add_argument(
        "--no-dissolve",
        action="store_true",
        help="If set, does NOT dissolve the road network into a single geometry.",
    )

    args = parser.parse_args()

    roads_path = Path(args.roads).expanduser().resolve()
    out_csv = Path(args.out).expanduser().resolve()
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    try:
        angles = [int(a.strip()) for a in args.angles.split(",") if a.strip() != ""]
        if not angles:
            raise ValueError
    except Exception:
        print("ERROR: --angles must be a comma-separated list of integers, e.g. 0,90,180,270")
        sys.exit(1)

    if not roads_path.exists():
        print(f"ERROR: Input shapefile not found:\n  {roads_path}")
        print("Tip: put your shapefile inside the 'roads/' folder or pass --roads /path/to/file.shp")
        sys.exit(1)

    # ----------------------------------------------------------
    # Load roads
    # ----------------------------------------------------------
    print(f"Loading roads shapefile:\n  {roads_path}")
    gdf = gpd.read_file(roads_path)

    if gdf.empty:
        print("ERROR: The shapefile is empty.")
        sys.exit(1)

    if gdf.crs is None:
        print("ERROR: The shapefile has no CRS defined (missing .prj).")
        print("Please define a CRS in your GIS software or re-export with a CRS.")
        sys.exit(1)

    # Optionally dissolve
    if not args.no_dissolve:
        gdf = gdf.copy()
        gdf["__dissolve__"] = 1
        gdf = gdf.dissolve(by="__dissolve__")

    # ----------------------------------------------------------
    # Reproject to a metric CRS (UTM auto-estimate)
    # ----------------------------------------------------------
    try:
        metric_crs = gdf.estimate_utm_crs()
        if metric_crs is None:
            raise ValueError("estimate_utm_crs() returned None")
    except Exception:
        print("WARNING: Could not estimate a UTM CRS automatically. Falling back to EPSG:3857.")
        metric_crs = "EPSG:3857"

    gdf_m = gdf.to_crs(metric_crs)

    # ----------------------------------------------------------
    # Fresh CSV: delete if exists and write header
    # ----------------------------------------------------------
    if out_csv.exists():
        out_csv.unlink()

    FIELDS = ["Latitude", "Longitude", "Angle", "Image_URL", "Image_Name"]

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        f.flush()

    print(f"Output CSV (fresh):\n  {out_csv}")
    print(f"Sampling every {args.distance} meters | Angles: {angles}")
    print(f"Metric CRS used: {metric_crs}")

    # ----------------------------------------------------------
    # Generate points and URLs
    # ----------------------------------------------------------
    captured_coords: List[Tuple[float, float]] = []
    seen = set()
    image_name = 1

    # Iterate over geometries
    for _, row in gdf_m.iterrows():
        geom = row.geometry
        for line in iter_lines(geom):
            if line.length == 0:
                continue

            pts = interpolate_points(line, args.distance)

            for pt in pts:
                # convert point to WGS84 for lat/lon
                pt_wgs = gpd.GeoSeries([pt], crs=gdf_m.crs).to_crs(epsg=4326).geometry.iloc[0]
                lat, lon = float(pt_wgs.y), float(pt_wgs.x)

                # Enforce spacing (within this run)
                if point_is_near(lat, lon, captured_coords, threshold_m=float(args.distance)):
                    continue

                captured_coords.append((lat, lon))

                for angle in angles:
                    key = make_key(lat, lon, angle)
                    if key in seen:
                        continue
                    seen.add(key)

                    image_url = generate_image_url(lat, lon, angle)

                    row_out = {
                        "Latitude": lat,
                        "Longitude": lon,
                        "Angle": int(angle),
                        "Image_URL": image_url,
                        "Image_Name": int(image_name),
                    }

                    # Append immediately after each URL
                    with out_csv.open("a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=FIELDS)
                        writer.writerow(row_out)
                        f.flush()

                    print(f"URL saved: {image_url} (Image_Name: {image_name})")
                    image_name += 1

    print("Done. CSV was written incrementally after each URL.")


if __name__ == "__main__":
    main()
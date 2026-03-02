# ==========================================================
# Import libraries
# ==========================================================
import geopandas as gpd
import pandas as pd
from geopy.distance import geodesic
from pathlib import Path
import csv

# ==========================================================
# Global Configuration
# ==========================================================
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR

ROADS_DIR = REPO_DIR / "roads"
OUTPUT_DIR = REPO_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

angles = [0, 90, 180, 270]

roads_dissolved = ROADS_DIR / "roads_lisbon_dissolved.shp"
url_log_file = OUTPUT_DIR / "lisbon_streetview_urls.csv"

# Load the roads shapefile
roads_in = ROADS_DIR / "roads_lisbon.shp"

# Create the 'dissolve' field and assign the value 1 to all the rows
gdf0 = gpd.read_file(roads_in)
gdf0["dissolve"] = 1

# Perform the dissolve based on the 'dissolve' field (all roads will be combined into a single geometry)
gdf_dissolved = gdf0.dissolve(by="dissolve")

# Save the result to a new shapefile
gdf_dissolved.to_file(roads_dissolved)
shapefile_path = roads_dissolved


# ==========================================================
# Helper Functions
# ==========================================================
def generate_image_url(lat, lon, angle):
    return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat},{lon}&heading={angle}"

def point_is_near(lat, lon, captured_coords, threshold_distance):
    new_point = (lat, lon)
    for existing in captured_coords:
        if geodesic(existing, new_point).meters < threshold_distance:
            return True
    return False

def interpolate_points(line, distance):
    points = []
    total_length = line.length
    num_segments = int(total_length // distance)

    for i in range(num_segments + 1):
        point = line.interpolate(i * distance)
        points.append(point)
    return points


# ==========================================================
# Main Logic
# ==========================================================
print("Loading shapefile...")
gdf = gpd.read_file(shapefile_path)
gdf = gdf.to_crs(epsg=3857)  # meters
point_distance = 30  # meters

captured_coords = []

# ----------------------------------------------------------
# (1) If CSV exists, delete it and start fresh
# ----------------------------------------------------------
if url_log_file.exists():
    url_log_file.unlink()

# Create fresh CSV with header
FIELDS = ["Latitude", "Longitude", "Angle", "Image_URL", "Image_Name"]
with url_log_file.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()

# Keep an in-memory set to avoid duplicates within this run
# Keyed by (lat, lon, angle) with rounding to avoid float noise
def make_key(lat, lon, angle):
    return (round(float(lat), 7), round(float(lon), 7), int(angle))

seen = set()

# Image_Name counter (starts at 1 and increases)
image_name = 1

# Iterate over each row in the shapefile
for idx, row in gdf.iterrows():
    geometry = row.geometry
    if geometry.is_empty:
        continue

    lines = geometry.geoms if geometry.geom_type == "MultiLineString" else [geometry]

    for line in lines:
        if line.length == 0:
            continue

        points = interpolate_points(line, point_distance)

        for point in points:
            # Convert back to WGS84 to generate URL (lat/lon)
            point_wgs84 = gpd.GeoSeries([point], crs=gdf.crs).to_crs(epsg=4326).geometry[0]
            lat, lon = float(point_wgs84.y), float(point_wgs84.x)

            # Enforce 30m spacing (within this run)
            if point_is_near(lat, lon, captured_coords, threshold_distance=point_distance):
                print(f"Coordinates ({lat:.6f}, {lon:.6f}) too close to a previously captured point. Skipping.")
                continue

            captured_coords.append((lat, lon))

            for angle in angles:
                key = make_key(lat, lon, angle)
                if key in seen:
                    continue
                seen.add(key)

                image_url = generate_image_url(lat, lon, angle)

                # ----------------------------------------------------------
                # (2) Append to CSV immediately (after each URL)
                # ----------------------------------------------------------
                row_out = {
                    "Latitude": lat,
                    "Longitude": lon,
                    "Angle": int(angle),
                    "Image_URL": image_url,
                    "Image_Name": int(image_name),
                }

                with url_log_file.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=FIELDS)
                    writer.writerow(row_out)
                    f.flush()

                print(f"URL saved: {image_url} (Image_Name: {image_name})")
                image_name += 1

print("Processing completed! Fresh CSV was created and saved after each URL.")


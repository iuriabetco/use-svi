import pandas as pd
import cv2
from pathlib import Path

# Disable OpenCL usage in OpenCV
cv2.ocl.setUseOpenCL(False)

# ==========================================================
# Base directory (portable: works as .py or in REPL)
# ==========================================================
if "__file__" in globals():
    BASE_DIR = Path(__file__).resolve().parent
else:
    BASE_DIR = Path.cwd()

images_folder = BASE_DIR / "images"
panoramas_folder = BASE_DIR / "panoramas"
csv_file = BASE_DIR / "outputs" / "streetview_urls_with_status_data.csv"
excel_file = BASE_DIR / "outputs" / "panoramas_metadata.xlsx"

panoramas_folder.mkdir(parents=True, exist_ok=True)
excel_file.parent.mkdir(parents=True, exist_ok=True)

print("BASE_DIR =", BASE_DIR)
print("images_folder =", images_folder)
print("csv_file =", csv_file)
print("panoramas_folder =", panoramas_folder)
print("excel_file =", excel_file)

# ==========================================================
# Helpers
# ==========================================================
def normalize_image_name(x) -> str:
    # 717.0 -> "717"
    if isinstance(x, float):
        return str(int(x))
    return str(x)

def coord_key(lat, lon, decimals=6):
    # rounding to avoid tiny float differences between consecutive rows
    return (round(float(lat), decimals), round(float(lon), decimals))

def has_valid_date(x) -> bool:
    """
    Returns True only if Image_Date is actually filled.
    Excludes empty strings, NaN-like strings, and 'None'.
    """
    if pd.isna(x):
        return False
    s = str(x).strip()
    if s == "":
        return False
    if s.lower() in {"nan", "none", "null"}:
        return False
    return True

def create_panorama_with_opencv(image_paths):
    """
    image_paths: list[Path]
    returns pano (numpy array) or None
    """
    images = [cv2.imread(str(p)) for p in image_paths]
    if any(img is None for img in images):
        return None

    try:
        stitcher = cv2.Stitcher_create()
        status, pano = stitcher.stitch(images)
    except cv2.error as e:
        print(f"OpenCV stitch exception: {e}")
        return None
    except Exception as e:
        print(f"Unexpected stitch exception: {e}")
        return None

    if status == cv2.Stitcher_OK and pano is not None:
        return pano
    return None

def save_metadata(metadata_out):
    """Save Excel progress after each successful panorama."""
    try:
        pd.DataFrame(metadata_out).to_excel(excel_file, index=False)
    except Exception as e:
        print(f"Warning: could not save Excel metadata: {e}")

def process_group(group_rows, panorama_counter, metadata_out):
    """
    group_rows: list of dicts with keys: lat, lon, date, image_name

    Rule:
      - ONLY use images with valid Image_Date
      - try stitch if >=2 valid images exist
      - if stitch fails: DO NOT SAVE anything
      - if stitch succeeds: save panorama + write metadata
    """
    if not group_rows:
        return panorama_counter

    lat = group_rows[0]["lat"]
    lon = group_rows[0]["lon"]

    # Keep only rows with valid date
    valid_rows = [r for r in group_rows if has_valid_date(r.get("date", ""))]

    if len(valid_rows) < 2:
        print(f"Skipping {lat}, {lon} — not enough dated images ({len(valid_rows)}).")
        return panorama_counter

    # Use first valid date as panorama metadata date
    date = valid_rows[0]["date"]

    # Collect existing image paths in the same order they appear in the file
    image_paths = []
    for r in valid_rows:
        p = images_folder / f"{r['image_name']}.png"
        if p.exists():
            image_paths.append(p)

    if len(image_paths) < 2:
        print(f"Skipping {lat}, {lon} — not enough existing dated images ({len(image_paths)}).")
        return panorama_counter

    pano = create_panorama_with_opencv(image_paths)

    if pano is None:
        print(f"Skipping {lat}, {lon} — stitch failed with {len(image_paths)} dated image(s).")
        return panorama_counter

    panorama_filename = f"{panorama_counter}.png"
    panorama_path = panoramas_folder / panorama_filename
    cv2.imwrite(str(panorama_path), pano)

    print(f"[{panorama_counter}] Panorama stitched ({len(image_paths)} dated imgs): {panorama_path}")

    metadata_out.append({
        "Latitude": lat,
        "Longitude": lon,
        "Image_Date": date,
        "Panorama_Name": panorama_filename,
        "Num_Images_Used": len(image_paths),
    })

    # Save after each successful panorama
    save_metadata(metadata_out)

    return panorama_counter + 1

# ==========================================================
# Load CSV (keeps file order)
# ==========================================================
df = pd.read_csv(csv_file)

# Normalize Image_Name
df["Image_Name"] = df["Image_Name"].apply(normalize_image_name)

# Make sure Image_Date exists and is string (kept for metadata only)
if "Image_Date" in df.columns:
    df["Image_Date"] = df["Image_Date"].astype(str).str.strip()
else:
    df["Image_Date"] = ""

# ==========================================================
# Sequential scan: group consecutive equal coordinates
# ==========================================================
panorama_counter = 1
panorama_metadata = []

current_group = []
current_coord = None  # (latR, lonR)

for _, row in df.iterrows():
    lat = float(row["Latitude"])
    lon = float(row["Longitude"])
    date = row["Image_Date"]
    image_name = row["Image_Name"]

    k = coord_key(lat, lon, decimals=6)

    if current_coord is None:
        current_coord = k

    # If coordinates changed, close previous group and start a new one
    if k != current_coord:
        panorama_counter = process_group(current_group, panorama_counter, panorama_metadata)
        current_group = []
        current_coord = k

    # Add current row to the ongoing group
    current_group.append({
        "lat": lat,
        "lon": lon,
        "date": date,
        "image_name": image_name,
    })

# Process the last group
panorama_counter = process_group(current_group, panorama_counter, panorama_metadata)

# ==========================================================
# Save metadata Excel
# ==========================================================
panorama_df = pd.DataFrame(panorama_metadata)
panorama_df.to_excel(excel_file, index=False)

print(f"Excel saved at: {excel_file}")
print(f"Total panoramas created: {len(panorama_metadata)}")
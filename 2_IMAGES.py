import re
import time
import pandas as pd
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth


# ==========================================================
# Opens a Google Street View URL, takes a screenshot and extracts the image capture date
# ==========================================================

def capture_streetview(driver, url, output_file):
    try:
        driver.get(url)

        # Accept cookies if button appears
        try:
            accept_button = driver.find_element(By.CSS_SELECTOR, "div.VtwTSb button")
            accept_button.click()
            time.sleep(1)
        except Exception:
            pass

        # Wait for Street View canvas
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "canvas"))
        )

        time.sleep(3)

        # -----------------------------
        # Extract image date
        # -----------------------------
        date_text = None
        try:
            body_text = driver.find_element(By.TAG_NAME, "body").text
            patterns = [
                r"\b\d{2}/\d{4}\b",
                r"\b\d{1,2}/\d{4}\b",
                r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
                r"\b\d{4}\b"
            ]
            for p in patterns:
                m = re.search(p, body_text, flags=re.IGNORECASE)
                if m:
                    date_text = m.group(0)
                    break
        except Exception:
            pass

        # -----------------------------
        # Hide everything except panorama canvas
        # -----------------------------
        driver.execute_script("""
            const canvases = Array.from(document.querySelectorAll('canvas'));
            if (canvases.length === 0) return;

            const area = (el) => {
                const r = el.getBoundingClientRect();
                return Math.max(0, r.width) * Math.max(0, r.height);
            };

            canvases.sort((a,b) => area(b) - area(a));
            const panoCanvas = canvases[0];

            const keep = new Set();
            let node = panoCanvas;
            while (node) {
                keep.add(node);
                node = node.parentElement;
            }

            const all = Array.from(document.body.querySelectorAll('*'));
            all.forEach(el => {
                if (!keep.has(el)) {
                    el.style.visibility = 'hidden';
                    el.style.pointerEvents = 'none';
                } else {
                    el.style.visibility = 'visible';
                }
            });

            document.documentElement.style.visibility = 'visible';
            document.body.style.visibility = 'visible';

            const itamenu = document.getElementById('itamenu');
            if (itamenu) {
                if (!itamenu.contains(panoCanvas) && !keep.has(itamenu)) {
                    itamenu.style.visibility = 'hidden';
                    itamenu.style.display = 'none';
                } else {
                    itamenu.style.background = 'transparent';
                    itamenu.style.boxShadow = 'none';
                    itamenu.style.border = 'none';
                    itamenu.style.filter = 'none';

                    Array.from(itamenu.querySelectorAll('*')).forEach(child => {
                        if (!keep.has(child) && child !== panoCanvas && !child.contains(panoCanvas)) {
                            child.style.visibility = 'hidden';
                            child.style.display = 'none';
                        }
                    });
                }
            }
        """)

        driver.save_screenshot(str(output_file))
        print(f"Image saved: {output_file}")

        return date_text

    except Exception as e:
        print(f"Error capturing image: {e}")
        return None


def main():
    # Base directory (where this script is located)
    base_dir = Path(__file__).resolve().parent

    # Portable paths
    csv_file = base_dir / "outputs" / "lisbon_streetview_urls.csv"
    output_folder = base_dir / "images"
    output_csv = base_dir / "outputs" / "lisbon_streetview_urls_with_status_data.csv"

    # Ensure folders exist
    output_folder.mkdir(parents=True, exist_ok=True)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    # Load CSV
    df = pd.read_csv(csv_file)

    df["Image_Name"] = df["Image_Name"].apply(
        lambda x: str(int(x)) if isinstance(x, float) else str(x)
    )

    if "Image_URL" not in df.columns or "Image_Name" not in df.columns:
        print("CSV is missing required columns.")
        return

    if "Image_Download_Status" not in df.columns:
        df["Image_Download_Status"] = "Not downloaded"
    if "Image_Date" not in df.columns:
        df["Image_Date"] = "Unavailable"

    # Selenium setup
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-webgl")
    options.add_argument("--use-gl=swiftshader")
    options.add_argument("--enable-unsafe-swiftshader")
    options.add_argument("--log-level=3")
    options.add_experimental_option("excludeSwitches", ["enable-logging"])

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=options
    )

    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
    )

    # Loop over URLs
    for index, row in df.iterrows():
        image_url = row["Image_URL"]
        image_name = row["Image_Name"]

        if "&pitch=" not in image_url:
            image_url += "&pitch=0"

        output_file = output_folder / f"{image_name}.png"

        try:
            date_text = capture_streetview(driver, image_url, output_file)

            df.at[index, "Image_Download_Status"] = "Downloaded"
            df.at[index, "Image_Date"] = date_text if date_text else "No date"

        except Exception as e:
            print(f"Error capturing image for {image_url}: {e}")
            df.at[index, "Image_Download_Status"] = "Failed"

        df.to_csv(output_csv, index=False)
        print(f"CSV updated: {output_csv}")

    driver.quit()
    print("Process completed.")


if __name__ == "__main__":
    main()




































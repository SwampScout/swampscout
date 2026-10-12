# Louisiana Swamp Scout v2 — Windows

This version adds:
- Interactive map where you draw a rectangle for any Louisiana area.
- Recent Sentinel-2 Level-2A scene search through the Microsoft Planetary Computer STAC catalog.
- Cloud-cover filtering and configurable date range.
- Automatic NDVI/NDWI raster analysis to flag wet-vegetation candidate patches.
- Approximate candidate GPS coordinates and CSV export.
- Official LDWF WMA/refuge/conservation-area boundary overlay and a best-effort USACE WMA overlay.

## Install and run (Windows 10/11)
1. Install Python 3.11 from https://www.python.org/downloads/windows/ . During setup, check **Add Python to PATH**.
2. Extract this ZIP into a normal folder, e.g. `C:\SwampScout`.
3. Open that folder in File Explorer.
4. Click the address bar, type `cmd`, and press Enter.
5. Run:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

The app should open in your browser. Keep the command window open while using it.

## How to scan
1. On the first map, use the rectangle tool to draw a box.
2. Click **Use drawn box**.
3. Choose look-back period, cloud cover, number of scenes, and patch thresholds in the sidebar.
4. Click **Scan selected area**.
5. Review the scene summary and candidate table. Download the CSV if useful.
6. Scroll to the public-land overlay map and inspect candidate pins relative to official boundary polygons.

## Notes / limitations
- Satellite source is Sentinel-2, not Google Earth. It provides open, repeat coverage at about 10 m for the visible/NIR bands; narrow channels and small holes may be missed.
- Cloud-cover percentage is scene-level and does not guarantee the selected box is cloud-free.
- Candidate coordinates are approximate because this starter implementation maps pixel positions linearly into the selected bounding box. Use them as leads, not navigation-grade GPS coordinates. The next engineering step should use the raster's true affine transform for exact pixel-to-coordinate placement.
- NDVI/NDWI thresholds are broad screening heuristics. Aquatic vegetation, cypress canopy, agricultural crops, algae, and land vegetation can overlap spectrally.
- A mapped WMA/refuge boundary is not legal proof of access or huntability. Confirm current LDWF and refuge rules before going.
- Large or complex areas may need to be split into smaller boxes.
- The program needs an internet connection. First-time package installation may take several minutes, especially for rasterio.
- The code uses public GIS endpoints; these can change or temporarily be unavailable.

## Data references
- LDWF official WMA GIS downloads: https://www.wlf.louisiana.gov/page/wma-gis-data-download
- LDWF WMA/refuge ArcGIS service: https://gis.wlf.la.gov/arcgis/rest/services/Wildlife_Services/LDWF_WMA_Refuge/MapServer
- USACE WMA ArcGIS service: https://gis.wlf.la.gov/arcgis/rest/services/Wildlife_Services/USACE_WMA_LA/MapServer
- Microsoft Planetary Computer STAC: https://planetarycomputer.microsoft.com/api/stac/v1

This is a scouting aid, not legal, land-title, navigation, or wildlife advice.

import json
import math
import requests
import numpy as np
import pandas as pd
import streamlit as st
import folium
from folium.plugins import Draw, Fullscreen, MeasureControl
from streamlit_folium import st_folium

st.set_page_config(page_title="Louisiana Swamp Scout", layout="wide")
st.title("Louisiana Swamp Scout — automatic scan")
st.caption("Draw a box anywhere in Louisiana, search recent Sentinel-2 satellite scenes, flag wetland-like vegetation, and overlay official public-land boundaries.")

LDWF_LAYER = "https://gis.wlf.la.gov/arcgis/rest/services/Wildlife_Services/LDWF_WMA_Refuge/MapServer/5/query"
USACE_ROOT = "https://gis.wlf.la.gov/arcgis/rest/services/Wildlife_Services/USACE_WMA_LA/MapServer"

with st.sidebar:
    st.header("Scan settings")
    days_back = st.selectbox("Imagery look-back", [30, 60, 90, 180, 365], index=3, format_func=lambda x: f"Past {x} days")
    max_cloud = st.slider("Maximum scene cloud cover", 0, 80, 25, 5)
    max_scenes = st.slider("Scenes to test", 1, 8, 4)
    st.caption("Sentinel-2 pixels are typically 10 m for the main bands. Small openings can be missed.")
    st.divider()
    st.header("Habitat thresholds")
    ndvi_min = st.slider("Vegetation NDVI minimum", 0.05, 0.75, 0.15, 0.01)
    ndwi_max = st.slider("Wetness filter (NDWI maximum)", -0.60, 0.50, 0.20, 0.01,
                         help="A broad filter: water/vegetation mixtures vary by season and location.")
    min_patch_ha = st.slider("Minimum candidate patch", 0.1, 20.0, 0.2, 0.1)
    st.divider()
    show_public = st.checkbox("Show LDWF WMA/refuge boundaries", value=True)
    show_usace = st.checkbox("Show USACE WMA boundaries", value=True)

st.info(
    "Imagery scan uses open Sentinel-2 data through Microsoft's Planetary Computer STAC catalog. "
    "This is not Google Earth imagery. Satellite indices flag candidates for visual review; they cannot prove "
    "a spot is navigable, has ducks, is publicly accessible, or is legal to hunt."
)

# Map interaction: user draws rectangle on a Louisiana-wide map.
if "bbox" not in st.session_state:
    st.session_state.bbox = [-91.6, 29.2, -89.0, 31.2]  # approximate south Louisiana starting extent
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None

st.subheader("1. Draw your scan area")
st.write("Use the rectangle tool on the map. Draw a box around any Louisiana area, then click **Use drawn box**.")
m = folium.Map(location=[30.4, -91.4], zoom_start=7, tiles="OpenStreetMap", control_scale=True)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri — World Imagery",
    name="Satellite basemap",
    overlay=False,
    control=True
).add_to(m)
Draw(
    export=False,
    draw_options={"polyline": False, "polygon": False, "circle": False, "marker": False,
                  "circlemarker": False, "rectangle": True},
    edit_options={"edit": True, "remove": True},
).add_to(m)
Fullscreen().add_to(m)
MeasureControl(position="topleft").add_to(m)
west, south, east, north = st.session_state.bbox
folium.Rectangle([[south, west], [north, east]], color="#ff7800", weight=2, fill=False,
                 tooltip="Current scan box").add_to(m)
map_data = st_folium(m, height=560, use_container_width=True, returned_objects=["all_drawings", "last_active_drawing"])

def bbox_from_drawing(drawing):
    try:
        geom = drawing.get("geometry", drawing)
        coords = geom.get("coordinates", [])
        # Rectangle GeoJSON polygon: first ring list of [lon,lat]
        ring = coords[0] if coords and isinstance(coords[0][0], (list, tuple)) else coords
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return [min(xs), min(ys), max(xs), max(ys)]
    except Exception:
        return None

drawn = None
if map_data:
    lad = map_data.get("last_active_drawing")
    if lad:
        drawn = bbox_from_drawing(lad)
    if not drawn:
        drawings = map_data.get("all_drawings") or []
        if drawings:
            drawn = bbox_from_drawing(drawings[-1])

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    if st.button("Use drawn box", type="primary", disabled=drawn is None):
        if drawn and drawn[2] > drawn[0] and drawn[3] > drawn[1]:
            st.session_state.bbox = drawn
            st.session_state.scan_results = None
            st.rerun()
with c2:
    if st.button("Reset to south Louisiana"):
        st.session_state.bbox = [-91.6, 29.2, -89.0, 31.2]
        st.session_state.scan_results = None
        st.rerun()
with c3:
    west, south, east, north = st.session_state.bbox
    st.write(f"**Selected bounds:** W {west:.5f}, S {south:.5f}, E {east:.5f}, N {north:.5f}")
    st.caption("Very large boxes may take longer to scan. Start with a box roughly 2–20 km across.")

def query_geojson(url, bbox, extra=None):
    w, s, e, n = bbox
    params = {
        "where": "1=1",
        "geometry": f"{w},{s},{e},{n}",
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    if extra:
        params.update(extra)
    r = requests.get(url, params=params, timeout=45)
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(payload["error"].get("message", str(payload["error"])))
    return payload

def get_usace_layers():
    r = requests.get(USACE_ROOT, params={"f": "json"}, timeout=20)
    r.raise_for_status()
    return r.json().get("layers", [])

def add_geojson_layer(map_obj, geojson, name, color):
    if geojson and geojson.get("features"):
        folium.GeoJson(
            geojson,
            name=name,
            style_function=lambda feat, c=color: {
                "color": c, "weight": 2, "fillColor": c, "fillOpacity": 0.12
            },
            tooltip=folium.GeoJsonTooltip(
                fields=[k for k in ["NAME", "Name", "WMA_NAME", "UNITNAME"] if k in (geojson["features"][0].get("properties") or {})][:2]
            ) if any(k in (geojson["features"][0].get("properties") or {}) for k in ["NAME", "Name", "WMA_NAME", "UNITNAME"]) else None
        ).add_to(map_obj)

st.divider()
st.subheader("2. Scan recent satellite imagery")
st.write("The scan searches recent Sentinel-2 Level-2A scenes over your box, filters cloudy scenes, then computes vegetation and wetness indices. Defaults are loosened to catch mixed water/vegetation marsh pixels; review the mask for false positives.")
scan = st.button("Scan selected area", type="primary")

if scan:
    try:
        import planetary_computer
        import pystac_client
        import rasterio
        from rasterio.windows import from_bounds
        from rasterio.enums import Resampling
        from shapely.geometry import box as shape_box
        from shapely.geometry import mapping
        from datetime import datetime, timedelta, timezone
        from rasterio.warp import transform_bounds

        west, south, east, north = st.session_state.bbox
        if east <= west or north <= south:
            st.error("The scan box is invalid.")
            st.stop()
        # Guard against very broad accidental selections.
        if (east-west) * (north-south) > 2.5:
            st.error("That box is very large. Draw a smaller area to keep downloads and processing manageable.")
            st.stop()

        progress = st.progress(0, text="Searching the satellite catalog…")
        catalog = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1")
        start = (datetime.now(timezone.utc) - timedelta(days=int(days_back))).date().isoformat()
        end = datetime.now(timezone.utc).date().isoformat()
        search = catalog.search(
            collections=["sentinel-2-l2a"],
            bbox=[west, south, east, north],
            datetime=f"{start}/{end}",
            query={"eo:cloud_cover": {"lt": int(max_cloud)}},
            max_items=int(max_scenes) * 5
        )
        items = list(search.items())
        items = sorted(items, key=lambda it: (it.properties.get("eo:cloud_cover", 100), it.datetime or datetime.min.replace(tzinfo=timezone.utc)))
        if not items:
            st.error("No suitable Sentinel-2 scenes were found in this date window. Increase the look-back period or cloud limit.")
            st.stop()

        # Select a few scenes. Prefer recent low-cloud scenes.
        items = sorted(items, key=lambda it: (-(it.datetime.timestamp() if it.datetime else 0), it.properties.get("eo:cloud_cover", 100)))[:int(max_scenes)]
        scene_rows, patch_rows = [], []
        best_preview = None
        best_scene = None
        best_mask = None
        for i, item in enumerate(items):
            progress.progress((i + 1) / (len(items) + 1), text=f"Reading scene {i+1}/{len(items)}: {item.id}")
            signed = planetary_computer.sign(item)
            # Read required COG bands, clipping to the selected geographic box.
            arrays = {}
            scene_transform = None
            scene_crs = None
            for band in ["B03", "B04", "B08"]:
                asset = signed.assets.get(band)
                if not asset:
                    raise RuntimeError(f"Band {band} is missing from scene {item.id}.")
                with rasterio.open(asset.href) as ds:
                    bounds = transform_bounds("EPSG:4326", ds.crs, west, south, east, north, densify_pts=15)
                    win = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
                    win = win.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
                    if win.width <= 0 or win.height <= 0:
                        arrays = {}
                        break
                    out_shape = (min(900, max(1, int(win.height))), min(900, max(1, int(win.width))))
                    data = ds.read(1, window=win, out_shape=out_shape,
                                   resampling=Resampling.bilinear).astype(np.float32)
                    arrays[band] = data
                    if band == "B03":
                        from affine import Affine
                        scene_transform = ds.window_transform(win) * Affine.scale(win.width / out_shape[1], win.height / out_shape[0])
                        scene_crs = ds.crs
            if not arrays:
                continue
            green, red, nir = arrays["B03"], arrays["B04"], arrays["B08"]
            shape = (min(a.shape[0] for a in arrays.values()), min(a.shape[1] for a in arrays.values()))
            green, red, nir = green[:shape[0], :shape[1]], red[:shape[0], :shape[1]], nir[:shape[0], :shape[1]]
            denom_ndvi = nir + red
            ndvi = np.divide(nir-red, denom_ndvi, out=np.zeros_like(nir), where=denom_ndvi != 0)
            denom_ndwi = green + nir
            ndwi = np.divide(green-nir, denom_ndwi, out=np.zeros_like(green), where=denom_ndwi != 0)
            # Candidate vegetation mask. The user-adjustable NDWI threshold is a permissive
            # screen, not proof of water. Keep lower NDVI mixed pixels so narrow marsh margins
            # and partially water-covered vegetation have a chance to appear.
            valid_reflectance = (nir > 0) & (green > 0) & (red >= 0)
            candidate = (ndvi >= float(ndvi_min)) & (ndwi <= float(ndwi_max)) & valid_reflectance

            # Exclude obvious open-water pixels: low vegetation signal plus a strongly
            # positive green/NIR NDWI. This helps suppress false candidate markers on lakes.
            open_water_like = (ndvi < max(float(ndvi_min) + 0.08, 0.23)) & (ndwi > 0.10)
            candidate = candidate & (~open_water_like)

            # Remove isolated noise but preserve narrow/irregular swamp-edge features.
            import cv2
            binary = candidate.astype(np.uint8)
            binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2,2), np.uint8))
            nlab, labels, stats, cents = cv2.connectedComponentsWithStats(binary, 8)
            pixel_area_m2 = 100  # approximate Sentinel-2 10 m pixels; area is a screening estimate
            min_pixels = max(1, int(float(min_patch_ha) * 10000 / pixel_area_m2))
            count_scene = 0
            for lab in range(1, nlab):
                x, y, ww, hh, area = stats[lab]
                if area < min_pixels:
                    continue
                cx, cy = cents[lab]
                # Convert the detected pixel center using the satellite raster's true transform,
                # rather than linearly stretching the selected map box over the raster array.
                px, py = scene_transform * (float(cx) + 0.5, float(cy) + 0.5)
                from rasterio.warp import transform as warp_transform
                lon_vals, lat_vals = warp_transform(scene_crs, "EPSG:4326", [px], [py])
                lon, lat = lon_vals[0], lat_vals[0]
                patch_rows.append({
                    "scene_date": item.datetime.date().isoformat() if item.datetime else "",
                    "scene_id": item.id,
                    "cloud_cover_pct": round(float(item.properties.get("eo:cloud_cover", 0)), 1),
                    "candidate_id": f"S{i+1}-P{count_scene+1}",
                    "center_latitude": round(lat, 6),
                    "center_longitude": round(lon, 6),
                    "estimated_patch_hectares": round(area * pixel_area_m2 / 10000, 2),
                    "pixel_width": int(ww), "pixel_height": int(hh),
                    "mean_ndvi": round(float(np.mean(ndvi[labels == lab])), 3),
                    "mean_ndwi": round(float(np.mean(ndwi[labels == lab])), 3),
                })
                count_scene += 1
            scene_rows.append({
                "scene_date": item.datetime.date().isoformat() if item.datetime else "",
                "scene_id": item.id,
                "cloud_cover_pct": round(float(item.properties.get("eo:cloud_cover", 0)), 1),
                "candidate_patches": count_scene
            })
            if best_preview is None:
                best_preview = {
                    "ndvi": ndvi, "ndwi": ndwi, "candidate": candidate,
                    "rgb": np.stack([green, red, nir], axis=-1)
                }
                best_scene = item
        progress.progress(1.0, text="Scan complete.")
        st.session_state.scan_results = {
            "scenes": scene_rows, "patches": patch_rows, "bbox": st.session_state.bbox,
            "preview": best_preview,
            "best_scene": best_scene.id if best_scene else None
        }
    except Exception as exc:
        st.error(f"Scan could not complete: {exc}")
        st.caption("Check your internet connection, try a smaller box, or use a longer look-back period. The first run may need to install the packages listed in requirements.txt.")

results = st.session_state.scan_results
if results:
    st.success(f"Scan complete. Processed {len(results['scenes'])} scenes.")
    st.subheader("Scene summary")
    st.dataframe(pd.DataFrame(results["scenes"]), use_container_width=True, hide_index=True)
    patches = pd.DataFrame(results["patches"])
    st.subheader("Candidate wet-vegetation patches")
    if patches.empty:
        st.info("No patches met the current thresholds. Try lowering the minimum patch size or changing the NDVI/NDWI settings.")
    else:
        st.dataframe(patches, use_container_width=True, hide_index=True)
        st.download_button("Download candidate GPS list (CSV)", patches.to_csv(index=False).encode("utf-8"),
                           file_name="louisiana_swamp_scout_candidates.csv", mime="text/csv")
    prev = results.get("preview")
    if prev is not None:
        st.subheader(f"Index preview — scene {results.get('best_scene')}")
        a, b, c = st.columns(3)
        with a:
            st.caption("NDVI: vegetation strength")
            st.image(np.clip((prev["ndvi"] + 1) * 127.5, 0, 255).astype(np.uint8), use_container_width=True)
        with b:
            st.caption("NDWI: broad water/wetness signal")
            st.image(np.clip((prev["ndwi"] + 1) * 127.5, 0, 255).astype(np.uint8), use_container_width=True)
        with c:
            st.caption("Candidate mask: white pixels matched")
            st.image((prev["candidate"].astype(np.uint8) * 255), use_container_width=True)

st.divider()
st.subheader("3. Official public-land boundary overlay")
st.write("The map below queries official LDWF WMA/refuge/conservation-area boundaries and, where available, USACE WMA boundaries for the selected box. Candidate pins now use the raster's geographic transform; spectral false positives over open water can still occur.")
try:
    west, south, east, north = st.session_state.bbox
    overlay_map = folium.Map(location=[(south+north)/2, (west+east)/2], zoom_start=11, tiles="OpenStreetMap")
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri — World Imagery", name="Satellite imagery", overlay=False
    ).add_to(overlay_map)
    folium.Rectangle([[south, west], [north, east]], color="#ff7800", weight=2, fill=False, tooltip="Scan box").add_to(overlay_map)
    if show_public:
        try:
            gj = query_geojson(LDWF_LAYER, st.session_state.bbox)
            add_geojson_layer(overlay_map, gj, "LDWF WMA / refuge / conservation areas", "#ffb000")
            st.write(f"LDWF boundary features intersecting box: {len(gj.get('features', []))}")
        except Exception as exc:
            st.warning(f"LDWF overlay could not load: {exc}")
    if show_usace:
        try:
            layers = get_usace_layers()
            matches = [layer for layer in layers if "wma" in layer.get("name", "").lower() or "wildlife" in layer.get("name", "").lower()]
            for layer in matches:
                url = f"{USACE_ROOT}/{layer['id']}/query"
                gj2 = query_geojson(url, st.session_state.bbox)
                add_geojson_layer(overlay_map, gj2, f"USACE — {layer['name']}", "#00b7a8")
        except Exception as exc:
            st.caption(f"USACE boundary layer unavailable: {exc}")
    if results:
        for _, row in pd.DataFrame(results["patches"]).iterrows():
            folium.CircleMarker(
                [row["center_latitude"], row["center_longitude"]],
                radius=5, color="#e63946", fill=True, fill_opacity=0.85,
                tooltip=f"{row['candidate_id']} · {row['estimated_patch_hectares']} ha · {row['scene_date']}"
            ).add_to(overlay_map)
    folium.LayerControl().add_to(overlay_map)
    st_folium(overlay_map, height=600, use_container_width=True, returned_objects=[])
except Exception as exc:
    st.error(f"Could not render public-land map: {exc}")

st.markdown("""
### Important field checks
- LDWF boundaries identify mapped management areas, **not every parcel of public water**. A location outside a WMA is not automatically public, and a location inside a boundary is not automatically open to hunting.
- Confirm current season rules, access restrictions, waterbody status, and any refuge-specific rules with the land manager before hunting.
- For Joyce WMA-style teal scouting, inspect open freshwater marsh, shallow-water edges, potholes, submerged vegetation, and channels manually. This tool's spectral classification is a first-pass filter—not a duck-use detector.
- Do not use drones on Louisiana WMAs; check current LDWF rules before any scouting activity.
""")

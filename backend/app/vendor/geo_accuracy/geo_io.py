"""
I/O helpers: DEM raster wrapper, CRS conversions, and CSV/TXT import+export for
GCPs, camera calibration and camera location. Keeps all rasterio/pyproj usage in
one place.

Every project input has a matching reader and writer here, so a project can be
written out as plain files and read back with nothing lost:

    GCPs         load_gcps_csv   / save_gcps_csv    (id,u,v,lat,lon,...)
    calibration  load_calib_csv  / save_calib_csv   (key,value)
    camera       load_camera_csv / save_camera_csv  (key,value)
"""
import csv
import os
import re
import numpy as np

try:
    import rasterio
    from pyproj import Transformer
except Exception:
    rasterio = None
    Transformer = None


class DEM:
    """Thin wrapper around a GeoTIFF DEM: bilinear Z lookup + CRS conversions."""

    def __init__(self, path):
        if rasterio is None:
            raise RuntimeError("rasterio not available")
        self.path = path
        self.ds = rasterio.open(path)
        self.arr = self.ds.read(1).astype(float)
        if self.ds.nodata is not None:
            self.arr[self.arr == self.ds.nodata] = np.nan
        self.epsg = self.ds.crs.to_epsg() if self.ds.crs else None
        if self.ds.crs is None or self.epsg is None:
            raise ValueError("DEM has no EPSG-coded CRS - assign one "
                             "(e.g. gdal_edit -a_srs EPSG:32637) and reload.")
        if self.ds.crs.is_geographic:
            raise ValueError("DEM CRS %s is geographic (degrees). Reproject to a metric "
                             "CRS first (e.g. gdalwarp -t_srs EPSG:32637) - ray marching "
                             "and PnP need metres." % self.ds.crs)
        self.res = float(self.ds.res[0])
        if not (0.05 <= self.res <= 1000.0):
            raise ValueError("DEM pixel size %.6g looks wrong for a metric CRS - "
                             "expected 0.05..1000 m per pixel." % self.res)
        self._to_ll = None
        self._to_xy = None

    def Z(self, x, y):
        """Bilinear bare-earth elevation at projected (x, y). NaN if outside.

        Interpolates between the four surrounding CELL CENTERS. (ds.index gives
        the containing cell and ds.xy its center, so the fractional offset there
        spans [-0.5, 0.5) - using it directly extrapolates and jumps at cell
        boundaries; instead work in continuous pixel coordinates.)"""
        col, row = (~self.ds.transform) * (float(x), float(y))
        col -= 0.5                      # integers now sit on cell centers
        row -= 0.5
        c0 = int(np.floor(col))
        r0 = int(np.floor(row))
        if not (0 <= r0 <= self.ds.height - 2 and 0 <= c0 <= self.ds.width - 2):
            return np.nan
        fc = col - c0
        fr = row - r0
        A = self.arr
        return (A[r0, c0] * (1 - fc) * (1 - fr) + A[r0, c0 + 1] * fc * (1 - fr) +
                A[r0 + 1, c0] * (1 - fc) * fr + A[r0 + 1, c0 + 1] * fc * fr)

    def lonlat_to_xy(self, lon, lat):
        if self._to_xy is None:
            self._to_xy = Transformer.from_crs(4326, self.epsg, always_xy=True)
        return self._to_xy.transform(lon, lat)

    def xy_to_latlon(self, x, y):
        if self._to_ll is None:
            self._to_ll = Transformer.from_crs(self.epsg, 4326, always_xy=True)
        lon, lat = self._to_ll.transform(x, y)
        return lat, lon


def _num(s):
    if s is None:
        return None
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)
        return float(m.group(0)) if m else None


GCP_COLUMNS = ("id", "name", "u", "v", "lat", "lon", "offset_m",
               "X", "Y", "Z", "excluded", "residual_px", "corr", "auto", "tuned")


def _truthy(s):
    return str(s).strip().lower() in ("1", "true", "yes", "y", "excluded", "excl", "x")


def load_gcps_csv(path):
    """Read GCPs from a field_points.csv-style file, or from a file this app wrote.

    Recognised columns (case-insensitive): id, name, latitude/lat, longitude/lon,
    offset_m/offset, u/v (pixel), X/Y/Z (projected metres), excluded, residual_px.
    A row needs either lat+lon or X+Y. Returns a list of dicts with the keys
    {id, name, lat, lon, offset, u, v, X, Y, Z, excl, res}; anything the file did
    not carry comes back as None.
    """
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        rdr = csv.DictReader(f)
        low = {c.lower().strip(): c for c in (rdr.fieldnames or [])}

        def col(*names):
            for nm in names:
                if nm in low:
                    return low[nm]
            return None

        c_id = col("id", "gcp", "gcp_id", "point_id")
        c_name = col("name")
        c_lat = col("latitude", "lat")
        c_lon = col("longitude", "lon")
        c_off = col("offset_m", "offset")
        c_u = col("u", "pixel_u", "px")
        c_v = col("v", "pixel_v", "py")
        c_x = col("x", "easting")
        c_y = col("y", "northing")
        c_z = col("z", "elevation", "height")
        c_ex = col("excluded", "excl")
        c_res = col("residual_px", "res", "residual")
        c_corr = col("corr", "correction", "checkpoint")
        c_auto = col("auto", "autogen")
        c_tuned = col("tuned")
        if not ((c_lat and c_lon) or (c_x and c_y)):
            raise ValueError("GCP CSV needs 'latitude'+'longitude' or 'X'+'Y' columns")
        for row in rdr:
            lat = _num(row.get(c_lat)) if c_lat else None
            lon = _num(row.get(c_lon)) if c_lon else None
            X = _num(row.get(c_x)) if c_x else None
            Y = _num(row.get(c_y)) if c_y else None
            if (lat is None or lon is None) and (X is None or Y is None):
                continue
            pid = _num(row.get(c_id)) if c_id else None
            rows.append(dict(
                id=(int(pid) if pid is not None else None),
                name=((row.get(c_name) or "").strip() if c_name else "") or "point",
                lat=lat, lon=lon,
                offset=(_num(row.get(c_off)) if c_off else None) or 0.0,
                u=(_num(row.get(c_u)) if c_u else None),
                v=(_num(row.get(c_v)) if c_v else None),
                X=X, Y=Y,
                Z=(_num(row.get(c_z)) if c_z else None),
                excl=(_truthy(row.get(c_ex)) if c_ex else False),
                res=(_num(row.get(c_res)) if c_res else None),
                # roles must survive the round-trip: without these, a
                # correction point reloaded from CSV silently re-enters the
                # solve, and the held-out accuracy check becomes circular
                corr=(_truthy(row.get(c_corr)) if c_corr else False),
                auto=(_truthy(row.get(c_auto)) if c_auto else False),
                tuned=(_truthy(row.get(c_tuned)) if c_tuned else False),
            ))
    return rows


def save_gcps_csv(path, points):
    """Write GCPs as  id,name,u,v,lat,lon,offset_m,X,Y,Z,excluded,residual_px.

    This is the app's GCP interchange file: it is both an output (what the solve
    used, with each point's residual) and a valid input to load_gcps_csv, so a
    saved project reloads its control points exactly as they were.
    """
    def fmt(v, spec):
        return "" if v is None else (spec % v)

    _ensure_parent(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(GCP_COLUMNS)
        for p in points:
            w.writerow([
                p.get("id", ""), p.get("name", ""),
                fmt(p.get("u"), "%.2f"), fmt(p.get("v"), "%.2f"),
                fmt(p.get("lat"), "%.8f"), fmt(p.get("lon"), "%.8f"),
                fmt(p.get("offset") or 0.0, "%.3f"),
                fmt(p.get("X"), "%.3f"), fmt(p.get("Y"), "%.3f"), fmt(p.get("Z"), "%.3f"),
                "1" if p.get("excl") else "0",
                fmt(p.get("res"), "%.3f"),
                "1" if p.get("corr") else "0",
                "1" if p.get("auto") else "0",
                "1" if p.get("tuned") else "0",
            ])
    return path


CALIB_KEYS = ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2", "k3", "img_w", "img_h")

# camera location + mounting, as stored in inputs/camera/*.csv
CAMERA_KEYS = ("cam_lat", "cam_lon", "Zoff", "X0", "Y0", "Z0",
               "heading", "tilt_down", "roll")
_CAMERA_ALIASES = {
    "cam_lat": "cam_lat", "lat": "cam_lat", "latitude": "cam_lat",
    "cam_lon": "cam_lon", "lon": "cam_lon", "longitude": "cam_lon",
    "zoff": "Zoff", "mast": "Zoff", "mast_height_m": "Zoff", "height": "Zoff",
    "height_m": "Zoff", "offset_m": "Zoff",
    "x0": "X0", "easting": "X0", "y0": "Y0", "northing": "Y0",
    "z0": "Z0", "elevation": "Z0", "ground_z": "Z0",
    "heading": "heading", "azimuth": "heading",
    "tilt_down": "tilt_down", "tilt": "tilt_down", "pitch": "tilt_down",
    "roll": "roll",
}


def _ensure_parent(path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _load_kv_csv(path):
    """Read a two-column key,value CSV -> {lowercased key: float}."""
    vals = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) < 2 or row[0].strip().startswith("#"):
                continue
            k = row[0].strip().lower()
            n = _num(row[1])
            if n is not None:
                vals[k] = n
    return vals


def _save_kv_csv(path, keys, values, title):
    """Write key,value rows. `title` must not contain a comma - csv.writer would
    quote the whole comment line."""
    _ensure_parent(path)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["# " + title])
        for k in keys:
            v = values.get(k)
            if isinstance(v, str):
                v = v.strip()
            if v is None or v == "":
                continue
            w.writerow([k, v])
    return path


def load_calib_csv(path):
    """Read intrinsics from a simple two-column key,value CSV.

    Keys (case-insensitive): fx, fy, cx, cy, k1, k2, p1, p2, k3, img_w, img_h.
    """
    return _load_kv_csv(path)


def save_calib_csv(path, values):
    """Write intrinsics as key,value - readable back by load_calib_csv."""
    return _save_kv_csv(path, CALIB_KEYS, values, "camera calibration (pixels)")


def load_camera_csv(path):
    """Read camera location / mounting from a key,value CSV.

    Accepts the canonical keys (cam_lat, cam_lon, Zoff, X0, Y0, Z0, heading,
    tilt_down, roll) and common spellings (latitude, longitude, mast_height_m,
    easting, northing, azimuth, pitch). Returns canonical keys only.
    """
    out = {}
    for k, v in _load_kv_csv(path).items():
        canon = _CAMERA_ALIASES.get(k)
        if canon:
            out[canon] = v
    if not out:
        raise ValueError("No camera fields found. Expected key,value rows such as "
                         "cam_lat,33.7797 / cam_lon,35.5695 / Zoff,2.5")
    return out


def save_camera_csv(path, values):
    """Write camera location + height (and pose angles) as key,value."""
    return _save_kv_csv(path, CAMERA_KEYS, values, "camera location + height + pose")


def load_calib_matlab_txt(path):
    """Parse a PyTrx/MATLAB-style calib .txt (IntrinsicMatrix stored transposed)."""
    t = open(path).read()

    def nums(s):
        return [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s)]

    Kml = np.array(nums(t.split("IntrinsicMatrix")[1].split("End")[0])[:9]).reshape(3, 3).T
    rad = nums(t.split("RadialDistortion")[1].split("TangentialDistortion")[0])
    tan = nums(t.split("TangentialDistortion")[1].split("IntrinsicMatrix")[0])
    return dict(
        fx=Kml[0, 0], fy=Kml[1, 1], cx=Kml[0, 2], cy=Kml[1, 2],
        k1=rad[0] if len(rad) > 0 else 0.0,
        k2=rad[1] if len(rad) > 1 else 0.0,
        k3=rad[2] if len(rad) > 2 else 0.0,
        p1=tan[0] if len(tan) > 0 else 0.0,
        p2=tan[1] if len(tan) > 1 else 0.0,
    )

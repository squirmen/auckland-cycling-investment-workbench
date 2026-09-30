"""Where STAND's data lives.

Raw and bulky inputs (Overture parquet, LINZ LiDAR rasters, aerial imagery) are not kept in the repository.
They live under a data root named by the STAND_DATA environment variable:

    export STAND_DATA=/path/to/stand-data

If STAND_DATA is not set, LD_LOC_DATA (the name STAND used before it moved into SPAN) is read instead, and
with neither set the data root is ./data/big next to this file, which is git-ignored.

Everything the pipeline writes is git-ignored as well, like SPAN's run outputs: the GeoParquet layers and run
summaries in data/derived (make all) and the map's data in web/data (make export).

Also here: require_derived() and require_raw(), which stop a script with the make targets to run when an input
is missing (instead of a pyarrow or rasterio traceback), and the DuckDB extension loader (duckdb_connect).
"""

import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent.parent
BIG = pathlib.Path(
    os.environ.get("STAND_DATA") or os.environ.get("LD_LOC_DATA") or HERE / "data" / "big"
)
RAW_OVERTURE = BIG / "overture"
RAW_LINZ = BIG / "linz"
DERIVED = HERE / "data" / "derived"
INPUTS = HERE / "data" / "inputs"
WEB_DATA = HERE / "web" / "data"
for p in (RAW_OVERTURE, RAW_LINZ, DERIVED, INPUTS, WEB_DATA):
    p.mkdir(parents=True, exist_ok=True)

# The make target that writes each GeoParquet layer in data/derived, in pipeline order.
STEPS = ["layers", "network", "demand", "model"]
WRITTEN_BY = {
    "layers": [
        "study_areas",
        "buildings",
        "uoa_buildings",
        "campus_footprint",
        "land_use",
        "infrastructure_points",
        "places",
        "segments",
        "edges",
        "connectors",
    ],
    "network": ["network_edges", "network_nodes"],
    "demand": ["destinations", "origins", "portals", "flow_edges", "flow_nodes"],
    "model": ["candidates", "hex_suitability_r11"],
}
_STEP_OF = {f"{name}.parquet": step for step, names in WRITTEN_BY.items() for name in names}


def ca_bundle():
    """The CA bundle named by SSL_CERT_FILE, REQUESTS_CA_BUNDLE or CURL_CA_BUNDLE, for networks that
    inspect TLS through a proxy. None means the system's own certificate store."""
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        path = os.environ.get(name)
        if path and os.path.exists(path):
            return path
    return None


def _some(items, n=4):
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def require_derived(script, *names):
    """Stop with a plain message, naming the make targets to run, if any of data/derived/<name>.parquet is missing.
    The targets run from the earliest missing layer's step through the last step this script reads from."""
    files = [n if n.endswith(".parquet") else f"{n}.parquet" for n in names]
    missing = [f for f in files if not (DERIVED / f).is_file()]
    if missing:
        first = min(STEPS.index(_STEP_OF.get(f, "layers")) for f in missing)
        last = max(STEPS.index(_STEP_OF.get(f, "layers")) for f in files)
        raise SystemExit(
            f"{script}: data/derived has no {_some(missing)}.\n"
            f"Run make {' '.join(STEPS[first : last + 1])} first (or make all)."
        )


def require_raw(script, *paths, fetch="make fetch"):
    """Stop with a plain message if a big input under the data root (STAND_DATA) is missing."""
    missing = [str(p) for p in paths if not pathlib.Path(p).exists()]
    if missing:
        raise SystemExit(
            f"{script}: missing input {_some(missing)} (data root {BIG}).\n"
            f"Set STAND_DATA to the folder that holds the big inputs, or run {fetch} first."
        )


def duckdb_extension_file(name):
    """The extension file shipped by the duckdb-extension-<name> Python package (duckdb_extension_<name>/extensions/
    v<version>/.../<name>.duckdb_extension) for the running DuckDB version, or None if that package or that version
    is not installed. A file built for another DuckDB version will not load, so only the matching one is returned."""
    import glob
    import importlib.util

    import duckdb

    spec = importlib.util.find_spec(f"duckdb_extension_{name}")
    for base in (spec.submodule_search_locations or []) if spec else []:
        hits = sorted(
            glob.glob(
                os.path.join(
                    glob.escape(base),
                    "extensions",
                    f"v{duckdb.__version__}",
                    "**",
                    f"{name}.duckdb_extension",
                ),
                recursive=True,
            )
        )
        if hits:
            return hits[0]
    return None


def load_duckdb_extensions(con, *names):
    """LOAD each DuckDB extension (spatial, httpfs) on connection con: from the pip-installed extension package
    when one matches the running DuckDB (requirements.txt pins them together), else DuckDB's own INSTALL, which
    downloads it once from extensions.duckdb.org into ~/.duckdb. Returns {name: where it came from}."""
    got = {}
    for name in names:
        path = duckdb_extension_file(name)
        if path:
            con.execute("LOAD '" + path.replace("'", "''") + "'")
            got[name] = path
        else:
            con.execute(f"INSTALL {name}; LOAD {name}")
            got[name] = "INSTALL"
    return got


def duckdb_connect(*extensions):
    """A new in-memory DuckDB connection with the named extensions loaded (see load_duckdb_extensions)."""
    import duckdb

    con = duckdb.connect()
    load_duckdb_extensions(con, *extensions)
    return con

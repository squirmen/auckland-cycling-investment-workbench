# STAND: secure bike parking siting for the University of Auckland campuses, part of SPAN
# (https://span.tfwelch.com/parking/uoa/). Run make in this folder, or make -C parking/uoa from SPAN's root.
#
# Big inputs live under $(STAND_DATA); see pipeline/paths.py. If STAND_DATA is not set, LD_LOC_DATA is used, and
# with neither set, ./data/big (git-ignored), which is also the scripts' own fallback.
PYTHON ?= python3
STAND_DATA ?= $(if $(LD_LOC_DATA),$(LD_LOC_DATA),$(CURDIR)/data/big)
export STAND_DATA

# MapLibre GL JS (the version index.html pins with Subresource Integrity) and Inter, fetched once from the npm
# registry into build/vendor by `make vendor`, for the offline one-file map (pipeline/build_standalone.py --offline).
# Use copies you already have with MAPLIBRE_DIST=/path/to/dist and STAND_INTER=/path/to/Inter-roman.var.woff2.
VENDOR_DIR := $(CURDIR)/build/vendor
MAPLIBRE_VERSION := 4.7.1
INTER_VERSION := 3.19.3
MAPLIBRE_DIST ?= $(VENDOR_DIR)/maplibre-gl-$(MAPLIBRE_VERSION)/dist
MAPLIBRE_CSS ?= $(MAPLIBRE_DIST)/maplibre-gl.css
STAND_INTER ?= $(VENDOR_DIR)/inter-ui-$(INTER_VERSION)/Inter-roman.var.woff2
export MAPLIBRE_DIST STAND_INTER

.PHONY: install fetch fetch-wide imagery layers network demand model basemap export docs site standalone all publish serve smoke vendor clean-derived

install:            ## Python dependencies
	$(PYTHON) -m pip install -r requirements.txt

fetch:              ## Overture themes + LINZ LiDAR + LINZ aerials for the study window (needs the network; ~600 MB to $(STAND_DATA))
	$(PYTHON) pipeline/fetch_overture.py
	$(PYTHON) pipeline/fetch_linz_elevation.py
	$(PYTHON) pipeline/fetch_linz_imagery.py
	$(PYTHON) pipeline/crop_imagery.py

fetch-wide:         ## Overture themes for the wide basemap window (Ponsonby to Orakei, waterfront to Epsom) to $(STAND_DATA)/overture_wide (~30 MB; needs the network)
	$(PYTHON) pipeline/fetch_overture.py --bbox 174.700,-36.925,174.840,-36.828 --out $(STAND_DATA)/overture_wide --lite divisions water land land_use segments buildings

imagery:            ## Re-trim the per-campus aerial patches in $(STAND_DATA)/linz (offline; make export copies them to web/data)
	$(PYTHON) pipeline/crop_imagery.py

layers:             ## Campus buildings, footprint, infrastructure, POIs, edge list
	$(PYTHON) pipeline/build_layers.py

network:            ## LTS, LiDAR grades, walking and cycling costs
	$(PYTHON) pipeline/build_network.py

demand:             ## Gravity model of cyclist approach flows
	$(PYTHON) pipeline/build_demand.py

model:              ## Candidates, indicators, exact k-dock optimisation, H3 r11 surface
	$(PYTHON) pipeline/site_model.py

basemap: fetch-wide ## Own-data basemap in web/data/basemap: Plain cartography, suburb and road labels, LINZ aerial mosaic (reads LINZ COGs online)
	$(PYTHON) pipeline/build_basemap.py

export:             ## GeoJSON + results.json for the web map, with the recommended sites' curated names
	$(PYTHON) pipeline/export_web.py
	$(PYTHON) pipeline/name_sites.py

docs:               ## The public method and recommendations pages in web/docs (set STAND_PRIVATE_TERMS for the private-term scan)
	$(PYTHON) pipeline/build_docs.py

site:               ## The /parking/ folder for span.tfwelch.com: ../build/site and ../build/span-parking-site.zip (rebuilds the docs first)
	$(PYTHON) pipeline/build_deploy.py

standalone:         ## One-file map that opens without a server (web/stand_standalone.html, git-ignored)
	$(PYTHON) pipeline/build_standalone.py

all: layers network demand model basemap export standalone   ## Everything after fetch (basemap needs the network). Steps stop with the make targets to run if an input layer is missing

publish:            ## Everything that ships, in order: export, docs, site, standalone
	$(MAKE) export
	$(MAKE) docs
	$(MAKE) site
	$(MAKE) standalone

serve:              ## Local preview of web/ at http://localhost:8765/
	cd web && $(PYTHON) -m http.server 8765

smoke:              ## Syntax checks only: the pipeline's Python and the map's JavaScript
	$(PYTHON) -m py_compile pipeline/*.py
	for f in web/js/*.js; do node --check "$$f" || exit 1; done

vendor:             ## MapLibre GL JS and Inter into build/vendor (npm registry; skipped when already there)
	@set -e; mkdir -p "$(VENDOR_DIR)"; \
	if [ -f "$(MAPLIBRE_DIST)/maplibre-gl.js" ] && [ -f "$(MAPLIBRE_CSS)" ]; then :; \
	elif [ "$(MAPLIBRE_DIST)" = "$(VENDOR_DIR)/maplibre-gl-$(MAPLIBRE_VERSION)/dist" ]; then \
	  T=$$(mktemp -d); (cd "$$T" && npm pack maplibre-gl@$(MAPLIBRE_VERSION) --silent >/dev/null && tar xzf maplibre-gl-$(MAPLIBRE_VERSION).tgz); \
	  rm -rf "$(VENDOR_DIR)/maplibre-gl-$(MAPLIBRE_VERSION)"; mv "$$T/package" "$(VENDOR_DIR)/maplibre-gl-$(MAPLIBRE_VERSION)"; rm -rf "$$T"; \
	else echo "vendor: no maplibre-gl.js and maplibre-gl.css in MAPLIBRE_DIST=$(MAPLIBRE_DIST)" >&2; exit 1; fi; \
	if [ ! -f "$(STAND_INTER)" ] && [ "$(STAND_INTER)" = "$(VENDOR_DIR)/inter-ui-$(INTER_VERSION)/Inter-roman.var.woff2" ]; then \
	  T=$$(mktemp -d); \
	  if (cd "$$T" && npm pack inter-ui@$(INTER_VERSION) --silent >/dev/null 2>&1 && tar xzf inter-ui-$(INTER_VERSION).tgz); then \
	    mkdir -p "$(VENDOR_DIR)/inter-ui-$(INTER_VERSION)"; cp "$$T/package/Inter (web)/Inter-roman.var.woff2" "$(STAND_INTER)"; \
	  else echo "vendor: Inter not fetched; the offline one-file map will use the system sans-serif" >&2; fi; rm -rf "$$T"; \
	fi; \
	echo "vendor: MapLibre $(MAPLIBRE_DIST); Inter $(STAND_INTER)"

clean-derived:      ## Remove data/derived (the GeoParquet layers and run summaries); make all rebuilds them
	rm -f data/derived/*.parquet data/derived/*.json

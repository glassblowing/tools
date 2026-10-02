# Tasks for keeping glassblowing.tools up to date. `make` lists them.
# The update-archive skill (.claude/skills/update-archive/SKILL.md) runs these.

PYTHON  ?= python3
ARCHIVE := $(PYTHON) scripts/archive.py
SITE    ?= /tmp/gbt-site
PORT    ?= 4000
# podman or docker, whichever is installed.
ENGINE  ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
# The same image the GitHub Pages deploy uses.
IMAGE   := ghcr.io/actions/jekyll-build-pages:v1.0.13

# Optional arguments:
#   VENDOR=id     limit links/photos to one vendor (required for catalog)
#   MAX_AGE=days  links: skip tools checked more recently (default 7; 0 = all)
#   REFRESH=1     photos: also re-check listings that already have a photo
#   DRY=1         links/photos/geocode: report only, don't write files
WRITE   := $(if $(DRY),,--write)
VFLAG   := $(if $(VENDOR),--vendor $(VENDOR))

.DEFAULT_GOAL := help
.PHONY: help validate build serve check links photos catalog geocode update

help: ## List the tasks
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-10s %s\n", $$1, $$2}'
	@echo "  Options: VENDOR=id  MAX_AGE=days  REFRESH=1  DRY=1  SITE=dir  PORT=n"

validate: ## Check tools, makers, categories and vendors line up
	$(ARCHIVE) validate

build: ## Build the site with the GitHub Pages image (into /tmp/gbt-site)
	@test -n "$(ENGINE)" || { echo "Neither podman nor docker is installed; the build can't be verified."; exit 1; }
	mkdir -p $(SITE)
	$(ENGINE) run --rm -v "$(CURDIR)":/src:Z,ro -v $(SITE):/out:Z \
		-e PAGES_REPO_NWO=glassblowing/tools -e JEKYLL_NO_GITHUB=1 \
		--entrypoint sh $(IMAGE) -c 'cd / && bundle exec github-pages build --source /src --destination /out'

serve: build ## Build, then preview at http://localhost:4000
	$(PYTHON) -m http.server --directory $(SITE) $(PORT)

check: validate build ## Validate and build (run before committing)

links: ## Re-check buy links and record last_checked
	$(ARCHIVE) links $(VFLAG) $(if $(MAX_AGE),--max-age $(MAX_AGE)) $(WRITE)

photos: ## Link seller photos for listings that lack one
	$(ARCHIVE) photos $(VFLAG) $(if $(REFRESH),--refresh) $(WRITE)

catalog: ## List a vendor's products and whether they're indexed (VENDOR=id)
	@test -n "$(VENDOR)" || { echo "usage: make catalog VENDOR=<vendor id>"; exit 1; }
	$(ARCHIVE) catalog $(VENDOR)

geocode: ## Add map coordinates for makers and shops with a location
	$(ARCHIVE) geocode $(WRITE)

update: links photos check ## Routine refresh: links, photos, validate, build

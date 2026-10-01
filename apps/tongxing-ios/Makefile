# Run from this directory, or use: make -C apps/tongxing-ios preview FILES=ContentView.swift
PREVIEW_ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
FILES ?=
VARIANTS ?= light,dark
INTERFACE_LOCALE ?= zh-Hans
SIMULATOR ?=
DERIVED_DATA ?=
DEVELOPER_DIR ?=
DRY_RUN ?= 0
export FILES VARIANTS INTERFACE_LOCALE SIMULATOR DERIVED_DATA DEVELOPER_DIR DRY_RUN

.PHONY: preview preview-list
preview:
	@set -- --files "$$FILES" --variants "$$VARIANTS" --interface-locale "$$INTERFACE_LOCALE"; \
	if [ -n "$$SIMULATOR" ]; then set -- "$$@" --simulator "$$SIMULATOR"; fi; \
	if [ -n "$$DERIVED_DATA" ]; then set -- "$$@" --derived-data "$$DERIVED_DATA"; fi; \
	if [ -n "$$DEVELOPER_DIR" ]; then set -- "$$@" --developer-dir "$$DEVELOPER_DIR"; fi; \
	if [ "$$DRY_RUN" = "1" ]; then set -- "$$@" --dry-run; fi; \
	python3 "$(PREVIEW_ROOT)scripts/preview.py" "$$@"

preview-list:
	@python3 "$(PREVIEW_ROOT)scripts/preview.py" --list

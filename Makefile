# iOS view screenshots: make preview FILES=ContentView.swift
.PHONY: preview preview-list
preview preview-list:
	@$(MAKE) --no-print-directory -C apps/tongxing-ios $@ DERIVED_DATA="$(if $(DERIVED_DATA),$(abspath $(DERIVED_DATA)))"

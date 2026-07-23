CONFIG ?= linux
V ?= 0
USE_COMPILER_WRAPPER ?= 0

include mk/common.mk
include mk/features.mk
include mk/platform.mk
include mk/sources.mk
include mk/rules.mk
-include local.mk

.DEFAULT_GOAL := linux

.PHONY: linux embedded tests run-tests generate clean print-config missing-input-demo app test-binary

linux:
	$(MAKE) CONFIG=linux app

embedded:
	$(MAKE) CONFIG=embedded app

tests:
	$(MAKE) CONFIG=tests test-binary

run-tests:
	$(MAKE) CONFIG=tests test-binary
	$(BUILD_ROOT)/tests/fixture_tests

generate:
	$(Q)$(PYTHON) tools/generate_build_files.py --platform $(PLATFORM) --configuration $(CONFIG) \
		--telemetry $(FEATURE_TELEMETRY) --fast-filter $(USE_FAST_FILTER) --output generated

app: generate $(OBJECTS) $(PLUGIN_LIBRARY)
	$(Q)$(CC_COMMAND) $(OBJECTS) $(PLUGIN_LIBRARY) $(LDFLAGS) -o $(APP_BINARY)

test-binary: generate $(TEST_OBJECTS) $(PLUGIN_LIBRARY)
	$(Q)$(CC_COMMAND) $(TEST_OBJECTS) $(PLUGIN_LIBRARY) $(LDFLAGS) -o $(TEST_BINARY)

print-config:
	@echo CONFIG=$(CONFIG)
	@echo PLATFORM=$(PLATFORM)
	@echo FEATURE_TELEMETRY=$(FEATURE_TELEMETRY)
	@echo USE_FAST_FILTER=$(USE_FAST_FILTER)
	@echo CHECKSUM_WIDTH=$(CHECKSUM_WIDTH)
	@echo SOURCES=$(SOURCES)

# Intentionally incomplete: no rule creates external_site_config.h.
missing-input-demo: generate
	$(Q)$(CC) $(CPPFLAGS) $(CFLAGS) -include generated/external_site_config.h \
		-c src/configuration/configuration.c -o $(BUILD_DIR)/missing-input-demo.o

clean:
	$(Q)rm -rf build
	$(Q)rm -f generated/build_config.h generated/version_info.c

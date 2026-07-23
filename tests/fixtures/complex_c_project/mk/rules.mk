$(GENERATED_HEADER) $(GENERATED_SOURCE): tools/generate_build_files.py templates/build_config.h.in templates/version_info.c.in
	$(Q)$(PYTHON) tools/generate_build_files.py --platform $(PLATFORM) --configuration $(CONFIG) \
		--telemetry $(FEATURE_TELEMETRY) --fast-filter $(USE_FAST_FILTER) --output generated

$(BUILD_DIR)/%.o: %.c $(GENERATED_HEADER)
	$(Q)mkdir -p $(dir $@)
	$(Q)$(CC_COMMAND) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(PLUGIN_LIBRARY): $(GENERATED_HEADER)
	$(Q)$(MAKE) -C src/plugins ROOT=$(CURDIR) CONFIG=$(CONFIG) BUILD_DIR=$(abspath $(BUILD_DIR)) \
		CC='$(CC)' USE_COMPILER_WRAPPER=$(USE_COMPILER_WRAPPER) V=$(V) all

-include $(OBJECTS:.o=.d) $(TEST_OBJECTS:.o=.d)

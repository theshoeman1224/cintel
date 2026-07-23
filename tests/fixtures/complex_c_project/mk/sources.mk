COMMON_SOURCES := \
	src/configuration/configuration.c \
	src/core/application.c \
	src/core/diagnostics.c \
	src/core/state_machine.c \
	src/drivers/sensor_driver.c \
	src/drivers/transport_driver.c \
	src/platform/common/platform_common.c \
	src/routing/router.c \
	src/shared/checksum.c \
	src/shared/conversion.c \
	src/include_cycle/cycle_user.c \
	third_party/src/vendor_stub.c \
	$(GENERATED_SOURCE)

ifeq ($(FEATURE_TELEMETRY),1)
FEATURE_SOURCES := src/telemetry/telemetry.c
else
FEATURE_SOURCES :=
endif

PRODUCTION_SOURCES := src/app/main.c $(COMMON_SOURCES) $(PLATFORM_SOURCE) $(FEATURE_SOURCES)
TEST_SUPPORT_SOURCES := tests/test_main.c tests/test_router.c tests/test_state_machine.c

SOURCES := $(PRODUCTION_SOURCES)
OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(SOURCES))
TEST_SOURCES := $(COMMON_SOURCES) $(PLATFORM_SOURCE) $(TEST_SUPPORT_SOURCES)
TEST_OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(TEST_SOURCES))

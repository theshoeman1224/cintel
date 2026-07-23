ROOT ?= ../..
CONFIG ?= linux
BUILD_DIR ?= $(ROOT)/build/$(CONFIG)
CC ?= gcc
AR ?= ar
V ?= 0
USE_COMPILER_WRAPPER ?= 0

ifeq ($(V),1)
Q :=
else
Q := @
endif

ifeq ($(USE_COMPILER_WRAPPER),1)
CC_COMMAND := $(ROOT)/tools/compiler_wrapper.sh $(CC)
else
CC_COMMAND := $(CC)
endif

SOURCES := plugin_registry.c plugin_alpha.c plugin_beta.c
OBJECTS := $(patsubst %.c,$(BUILD_DIR)/plugins/%.o,$(SOURCES))
TARGET := $(BUILD_DIR)/libplugins.a
CPPFLAGS := -I$(ROOT)/include -I$(ROOT)/generated -isystem $(ROOT)/third_party/include
CPPFLAGS += -include $(ROOT)/generated/build_config.h
CFLAGS := -std=c11 -g -Wall -Wextra -Wpedantic -fPIC -MMD -MP

ifeq ($(CONFIG),linux)
CPPFLAGS += -DPLATFORM_LINUX -DFEATURE_TELEMETRY=1 -DUSE_FAST_FILTER=1 -DCHECKSUM_WIDTH=32
CFLAGS += -O2
else ifeq ($(CONFIG),embedded)
CPPFLAGS += -DPLATFORM_EMBEDDED -DFEATURE_TELEMETRY=0 -DUSE_FAST_FILTER=0 -DCHECKSUM_WIDTH=16
CFLAGS += -O0
else
CPPFLAGS += -DPLATFORM_LINUX -DUNIT_TEST -DFEATURE_TELEMETRY=0 -DUSE_FAST_FILTER=1 -DCHECKSUM_WIDTH=32
CFLAGS += -O1
endif

.PHONY: all clean
all: $(TARGET)

$(TARGET): $(OBJECTS)
	$(Q)$(AR) rcs $@ $(OBJECTS)

$(BUILD_DIR)/plugins/%.o: %.c
	$(Q)mkdir -p $(dir $@)
	$(Q)env FIXTURE_MODULE=plugins $(CC_COMMAND) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

clean:
	$(Q)rm -rf $(BUILD_DIR)/plugins $(TARGET)

-include $(OBJECTS:.o=.d)

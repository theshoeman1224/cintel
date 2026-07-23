CC := gcc
PYTHON ?= python3
BUILD_ROOT ?= build
BUILD_DIR := $(BUILD_ROOT)/$(CONFIG)
APP_BINARY := $(BUILD_DIR)/sensor_router
TEST_BINARY := $(BUILD_DIR)/fixture_tests
GENERATED_HEADER := generated/build_config.h
GENERATED_SOURCE := generated/version_info.c
PLUGIN_LIBRARY := $(BUILD_DIR)/libplugins.a

ifeq ($(V),1)
Q :=
else
Q := @
endif

WRAPPER := $(CURDIR)/tools/compiler_wrapper.sh
ifeq ($(USE_COMPILER_WRAPPER),1)
CC_COMMAND := $(WRAPPER) $(CC)
else
CC_COMMAND := $(CC)
endif

CPPFLAGS += -Iinclude -Igenerated -isystem third_party/include
CPPFLAGS += -include $(GENERATED_HEADER) -DLEGACY_MODE -ULEGACY_MODE
CFLAGS += -std=c11 -g -Wall -Wextra -Wpedantic -fPIC -MMD -MP
LDFLAGS :=

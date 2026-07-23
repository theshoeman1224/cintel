ifeq ($(CONFIG),embedded)
PLATFORM := embedded
PLATFORM_SOURCE := src/platform/embedded/platform_embedded.c
else
PLATFORM := linux
PLATFORM_SOURCE := src/platform/linux/platform_linux.c
endif

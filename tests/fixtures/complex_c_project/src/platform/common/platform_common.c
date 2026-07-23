#include "cintel_fixture/platform.h"

struct PlatformContext {
    int initialized;
    unsigned int event_count;
};

static struct PlatformContext s_platform_context;

PlatformContext *platform_context(void)
{
    return &s_platform_context;
}

void platform_mark_initialized(int initialized)
{
    s_platform_context.initialized = initialized;
}

/* CINTEL_EXPECT[WEAK_SYMBOL]: symbol=platform_event_hook */
__attribute__((weak)) void platform_event_hook(int event_id)
{
    (void)event_id;
    ++s_platform_context.event_count;
}

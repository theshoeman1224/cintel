#include "cintel_fixture/platform.h"

int platform_initialize(void)
{
    platform_mark_initialized(1);
    return 0;
}

void platform_shutdown(void)
{
    platform_mark_initialized(0);
}

const char *platform_name(void)
{
    return "linux";
}

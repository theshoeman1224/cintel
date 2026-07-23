#include "cintel_fixture/diagnostics.h"
#include "cintel_fixture/platform.h"

/* CINTEL_EXPECT[VOLATILE_GLOBAL]: symbol=g_diagnostic_event_count; storage=definition */
volatile unsigned int g_diagnostic_event_count = 0U;
static int s_last_event = 0;

void diagnostics_record_event(int event_id)
{
    ++g_diagnostic_event_count;
    s_last_event = event_id;
    platform_event_hook(event_id);
}

unsigned int diagnostics_event_count(void)
{
    return g_diagnostic_event_count;
}

int diagnostics_last_event(void)
{
    return s_last_event;
}

#include <stdio.h>

#include "cintel_fixture/application.h"
#include "cintel_fixture/diagnostics.h"
#include "cintel_fixture/platform.h"

/* CINTEL_EXPECT[FUNCTION_DEFINITION]: symbol=main; visibility=external */
int main(void)
{
    AppStatus status;

    status = application_initialize();
    if (status == APP_STATUS_OK) {
        status = application_run(4U);
    }

    printf("fixture platform=%s version=%s events=%u status=%d\n",
           platform_name(), fixture_version_string(), diagnostics_event_count(), (int)status);
    platform_shutdown();
    return status == APP_STATUS_OK ? 0 : 1;
}

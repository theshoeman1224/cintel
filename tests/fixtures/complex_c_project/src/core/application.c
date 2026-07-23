/* CINTEL_EXPECT[INCLUDE_RELATIONSHIP]: from=src/core/application.c; to=cintel_fixture/application.h */
#include "cintel_fixture/application.h"
#include "cintel_fixture/configuration.h"
#include "cintel_fixture/diagnostics.h"
#include "cintel_fixture/platform.h"
#include "cintel_fixture/plugin.h"
#include "cintel_fixture/router.h"
#include "cintel_fixture/sensor.h"
#include "cintel_fixture/state_machine.h"
#include "cintel_fixture/telemetry.h"

/* CINTEL_EXPECT[GLOBAL_DECLARATION]: symbol=g_application_state; storage=definition */
AppStatus g_application_state = APP_STATUS_INITIALIZATION_FAILED;

/* CINTEL_EXPECT[FUNCTION_DEFINITION]: symbol=application_initialize; visibility=external */
AppStatus application_initialize(void)
{
    FixtureConfiguration configuration;

    g_application_state = APP_STATUS_INITIALIZATION_FAILED;

    /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_initialize; callee=configuration_load */
    if (configuration_load(&configuration) != 0) {
        diagnostics_record_event(100);
        return g_application_state;
    }
    /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_initialize; callee=platform_initialize */
    if (platform_initialize() != 0) {
        diagnostics_record_event(101);
        return g_application_state;
    }
    /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_initialize; callee=sensor_initialize */
    if (sensor_initialize() != 0) {
        diagnostics_record_event(102);
        platform_shutdown();
        return g_application_state;
    }
    /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_initialize; callee=router_initialize */
    if (router_initialize() != 0 || plugin_register_all() != 0) {
        diagnostics_record_event(103);
        platform_shutdown();
        return g_application_state;
    }
    state_machine_reset();

#if FEATURE_TELEMETRY
    /* CINTEL_EXPECT[CONDITIONAL_CALL]: caller=application_initialize; callee=telemetry_initialize; condition=FEATURE_TELEMETRY */
    if (telemetry_initialize() != 0) {
        diagnostics_record_event(104);
        platform_shutdown();
        return g_application_state;
    }
#endif

    /* CINTEL_EXPECT[GLOBAL_WRITE]: function=application_initialize; symbol=g_application_state */
    g_application_state = APP_STATUS_OK;
    return g_application_state;
}

AppStatus application_run(unsigned int iterations)
{
    unsigned int index;

    if (g_application_state != APP_STATUS_OK) {
        return g_application_state;
    }
    for (index = 0U; index < iterations; ++index) {
        Message message;
        RouteResult route_result;

        /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_run; callee=sensor_poll */
        if (sensor_poll(&message) != 0) {
            diagnostics_record_event(200);
            g_application_state = APP_STATUS_RUNTIME_ERROR;
            break;
        }
        /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_run; callee=router_dispatch */
        route_result = router_dispatch(&message);
        /* CINTEL_EXPECT[DIRECT_CALL]: caller=application_run; callee=state_machine_process */
        if (state_machine_process(&message, route_result) == MACHINE_STATE_FAULT) {
            diagnostics_record_event(201);
            g_application_state = APP_STATUS_RUNTIME_ERROR;
            break;
        }
#if FEATURE_TELEMETRY
        /* CINTEL_EXPECT[CONDITIONAL_CALL]: caller=application_run; callee=telemetry_publish; condition=FEATURE_TELEMETRY */
        telemetry_publish(&message);
#endif
    }
    return g_application_state;
}

/* CINTEL_EXPECT[GLOBAL_READ]: function=application_get_state; symbol=g_application_state */
AppStatus application_get_state(void)
{
    return g_application_state;
}

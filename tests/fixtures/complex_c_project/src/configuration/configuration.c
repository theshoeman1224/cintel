#include "cintel_fixture/configuration.h"

static FixtureConfiguration s_configuration;

/* CINTEL_EXPECT[DUPLICATE_STATIC_NAME]: symbol=normalize_value; distinct_by=file */
static int normalize_value(int value)
{
    return fixture_clamp(value, 0, 100);
}

/* CINTEL_EXPECT[DECLARATION_DEFINITION_LINK]: symbol=configuration_load; header=configuration.h */
int configuration_load(FixtureConfiguration *configuration)
{
    if (configuration == NULL) {
        return -1;
    }
    configuration->limits.minimum = normalize_value(-5);
    configuration->limits.maximum = normalize_value(120);
    configuration->retry_count = 3U;
    configuration->telemetry_enabled = FEATURE_TELEMETRY;
    s_configuration = *configuration;
    return 0;
}

/* CINTEL_EXPECT[STATIC_SYMBOL]: symbol=s_configuration; scope=file */
const FixtureConfiguration *configuration_current(void)
{
    return &s_configuration;
}

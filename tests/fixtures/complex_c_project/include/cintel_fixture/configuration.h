#ifndef CINTEL_FIXTURE_CONFIGURATION_H
#define CINTEL_FIXTURE_CONFIGURATION_H

#include "build_config.h"
#include "cintel_fixture/types.h"

int configuration_load(FixtureConfiguration *configuration);
const FixtureConfiguration *configuration_current(void);

#endif

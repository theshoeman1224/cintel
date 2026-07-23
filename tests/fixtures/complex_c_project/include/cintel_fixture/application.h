#ifndef CINTEL_FIXTURE_APPLICATION_H
#define CINTEL_FIXTURE_APPLICATION_H

#include "cintel_fixture/types.h"

/* CINTEL_EXPECT[GLOBAL_DECLARATION]: symbol=g_application_state; storage=extern */
extern AppStatus g_application_state;

/* CINTEL_EXPECT[FUNCTION_DECLARATION]: symbol=application_initialize; visibility=external */
AppStatus application_initialize(void);
AppStatus application_run(unsigned int iterations);
AppStatus application_get_state(void);
const char *fixture_version_string(void);

#endif

#ifndef CINTEL_FIXTURE_PLATFORM_H
#define CINTEL_FIXTURE_PLATFORM_H

typedef struct PlatformContext PlatformContext;

int platform_initialize(void);
void platform_shutdown(void);
const char *platform_name(void);
PlatformContext *platform_context(void);
void platform_mark_initialized(int initialized);
void platform_event_hook(int event_id);

#endif

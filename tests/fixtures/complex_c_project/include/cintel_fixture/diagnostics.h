#ifndef CINTEL_FIXTURE_DIAGNOSTICS_H
#define CINTEL_FIXTURE_DIAGNOSTICS_H

/* CINTEL_EXPECT[VOLATILE_GLOBAL]: symbol=g_diagnostic_event_count */
extern volatile unsigned int g_diagnostic_event_count;

void diagnostics_record_event(int event_id);
unsigned int diagnostics_event_count(void);
int diagnostics_last_event(void);

#endif

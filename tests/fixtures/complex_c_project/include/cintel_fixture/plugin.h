#ifndef CINTEL_FIXTURE_PLUGIN_H
#define CINTEL_FIXTURE_PLUGIN_H

#include "cintel_fixture/router.h"

typedef struct PluginDescriptor {
    unsigned int identifier;
    const char *name;
    MessageHandlerCallback handler;
} PluginDescriptor;

/* CINTEL_EXPECT[MACRO_DEFINITION]: symbol=DEFINE_PLUGIN_HANDLER; kind=function_generator */
#define DEFINE_PLUGIN_HANDLER(name, identifier_value)                                      \
    RouteResult name##_handle(const Message *message, void *context)                       \
    {                                                                                       \
        (void)context;                                                                       \
        return message != NULL && message->identifier == (identifier_value)                 \
                   ? ROUTE_RESULT_HANDLED                                                    \
                   : ROUTE_RESULT_DROPPED;                                                   \
    }

const PluginDescriptor *plugin_registry(size_t *count);
int plugin_register_all(void);
RouteResult plugin_alpha_handle(const Message *message, void *context);
RouteResult plugin_beta_handle(const Message *message, void *context);

#endif

#ifndef CINTEL_FIXTURE_ROUTER_H
#define CINTEL_FIXTURE_ROUTER_H

#include "cintel_fixture/message.h"

/* CINTEL_EXPECT[TYPE_DEFINITION]: symbol=MessageHandlerCallback; kind=callback_typedef */
typedef RouteResult (*MessageHandlerCallback)(const Message *message, void *context);

typedef struct MessageHandler {
    MessageType accepted_type;
    MessageHandlerCallback handler;
    void *context;
} MessageHandler;

int router_initialize(void);
int router_register_handler(const MessageHandler *handler);
RouteResult router_dispatch(const Message *message);
RouteResult router_classify_message(const Message *message);
unsigned int router_dispatch_count(void);

#endif

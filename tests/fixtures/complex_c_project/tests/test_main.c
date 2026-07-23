#include <stdio.h>

int test_router(void);
int test_state_machine(void);

int main(void)
{
    int failures = 0;

    failures += test_router();
    failures += test_state_machine();
    if (failures == 0) {
        puts("fixture tests passed");
    }
    return failures == 0 ? 0 : 1;
}

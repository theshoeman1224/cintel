#include "project.h"

int project_value(void) {
    return 42;
}

int main(void) {
    return project_value() == 42 ? 0 : 1;
}

#include "unity.h"

void setUp(void) {}
void tearDown(void) {}

void run_frame_tests(void);
void run_reg_tests(void);
void run_device_tests(void);

int main(void)
{
    UNITY_BEGIN();
    run_frame_tests();
    run_reg_tests();
    run_device_tests();
    return UNITY_END();
}

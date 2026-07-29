#include "unity.h"

void setUp(void) {}
void tearDown(void) {}

void run_frame_tests(void);
void run_reg_tests(void);
void run_device_tests(void);
void run_lines_tests(void);
void run_stepgen_tests(void);
void run_cobs_tests(void);
void run_rpc_frame_tests(void);
void run_rpc_tests(void);

int main(void)
{
    UNITY_BEGIN();
    run_frame_tests();
    run_reg_tests();
    run_device_tests();
    run_lines_tests();
    run_stepgen_tests();
    run_cobs_tests();
    run_rpc_frame_tests();
    run_rpc_tests();
    return UNITY_END();
}

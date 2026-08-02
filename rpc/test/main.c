#include "unity.h"

void setUp(void) {}
void tearDown(void) {}

void run_cobs_tests(void);
void run_rpc_frame_tests(void);

int main(void)
{
    UNITY_BEGIN();
    run_cobs_tests();
    run_rpc_frame_tests();
    return UNITY_END();
}

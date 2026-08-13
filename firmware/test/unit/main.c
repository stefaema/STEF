#include "unity.h"

void setUp(void)
{
}
void tearDown(void)
{
}

void run_rpc_tests(void);
void run_ramp_tests(void);

int main(void)
{
    UNITY_BEGIN();
    run_rpc_tests();
    run_ramp_tests();
    return UNITY_END();
}

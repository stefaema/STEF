#include "unity.h"

void setUp(void)
{
}
void tearDown(void)
{
}

void run_rpc_tests(void);

int main(void)
{
    UNITY_BEGIN();
    run_rpc_tests();
    return UNITY_END();
}

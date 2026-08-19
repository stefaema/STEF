#include "fw_api.h"

#include <stdio.h>

int main(void)
{
    printf("fw_api %s %s, %zu bytes max frame\n", FW_API_BACKEND, FW_API_VERSION,
           (size_t)RPC_MAX_FRAME);
    return 0;
}

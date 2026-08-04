#include "rpc_api.h"

#include <stdio.h>

int main(void)
{
    printf("rpc_api protocol v%d, %zu bytes max frame\n", RPC_PROTOCOL_VERSION,
           (size_t)RPC_MAX_FRAME);
    return 0;
}

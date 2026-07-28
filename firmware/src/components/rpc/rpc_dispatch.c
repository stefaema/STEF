#include "rpc_dispatch.h"

#include <stddef.h>

/*
 * One table per namespace, indexed by method number, so a method the protocol
 * names but this build does not implement is a NULL entry rather than a gap in
 * a switch. Registration is what keeps this file from naming any handler, and
 * therefore from linking against anything a handler needs.
 */
typedef struct {
    const rpc_handler_fn *methods;
    size_t                count;
} rpc_namespace_t;

static rpc_namespace_t s_namespaces[RPC_NS_MAX];

bool rpc_register(uint8_t ns, const rpc_handler_fn *methods, size_t count)
{
    if (ns >= RPC_NS_MAX || methods == NULL) {
        return false;
    }

    s_namespaces[ns].methods = methods;
    s_namespaces[ns].count   = count;
    return true;
}

void rpc_reset_registry(void)
{
    for (size_t i = 0; i < RPC_NS_MAX; i++) {
        s_namespaces[i].methods = NULL;
        s_namespaces[i].count   = 0;
    }
}

rpc_status_t rpc_dispatch(const rpc_req_t *req, rpc_reader_t *args,
                          rpc_writer_t *ret, size_t ret_mark)
{
    if (req == NULL || args == NULL || ret == NULL) {
        return RPC_INTERNAL;
    }

    if (req->ns >= RPC_NS_MAX) {
        return RPC_NO_METHOD;
    }

    const rpc_namespace_t *ns = &s_namespaces[req->ns];
    if (ns->methods == NULL || req->method >= ns->count ||
        ns->methods[req->method] == NULL) {
        return RPC_NO_METHOD;
    }

    rpc_status_t status = ns->methods[req->method](args, ret);

    /*
     * Two ways the frame itself was wrong, both meaning the ends disagree
     * about this method's arguments rather than that the call failed. Checked
     * after the handler, because the handler is what knows how many arguments
     * there were meant to be.
     */
    if (!args->ok) {
        status = RPC_BAD_FRAME;
    } else if (status == RPC_OK && !rpc_r_done(args)) {
        status = RPC_BAD_FRAME;
    }

    if (status != RPC_OK) {
        rpc_w_rewind(ret, ret_mark);
    }

    return status;
}

#include "rpc_dispatch.h"

#include <stddef.h>
#include <string.h>

/*
 * One table per namespace, indexed by method number. A method the protocol names
 * but this build does not serve is a zeroed entry.
 */
typedef struct {
    const rpc_method_t *methods;
    size_t              count;
} rpc_namespace_t;

static rpc_namespace_t s_namespaces[RPC_NS_MAX];

bool rpc_register(uint8_t ns, const rpc_method_t *methods, size_t count)
{
    if (ns >= RPC_NS_MAX || methods == NULL) {
        return false;
    }

    /*
     * Checked once at start-up, so dispatch never has to ask whether a reply
     * fits.
     */
    for (size_t i = 0; i < count; i++) {
        if (methods[i].args_len > RPC_MAX_PAYLOAD || methods[i].ret_len > RPC_MAX_PAYLOAD) {
            return false;
        }
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

/* A zeroed entry is a method number the protocol reserves and this build does
 * not serve. Which half of the union to test follows from the tag. */
static bool implemented(const rpc_method_t *m)
{
    if (m->variable) {
        return m->fn.var != NULL;
    }
    return m->fn.fixed != NULL;
}

rpc_status_t rpc_dispatch(uint8_t ns, uint8_t method, const void *args, size_t args_len, void *ret,
                          size_t *ret_len)
{
    if (ret_len == NULL || (ret == NULL && args == NULL)) {
        return RPC_INTERNAL;
    }

    *ret_len = 0;

    if (ns >= RPC_NS_MAX) {
        return RPC_NO_METHOD;
    }

    const rpc_namespace_t *space = &s_namespaces[ns];
    if (space->methods == NULL || method >= space->count) {
        return RPC_NO_METHOD;
    }

    const rpc_method_t *m = &space->methods[method];
    if (!implemented(m)) {
        return RPC_NO_METHOD;
    }

    /*
     * Cleared first, since payloads have padding and the reply buffer is reused.
     * An unchanged answer keeps the same CRC, and nothing unwritten reaches the
     * caller.
     */
    if (ret != NULL && m->ret_len > 0U) {
        memset(ret, 0, m->ret_len);
    }

    rpc_status_t status;

    if (m->variable) {
        /*
         * A minimum, since the head of the payload holds the count that settles
         * the real length. The handler checks that count.
         */
        if (args_len < m->args_len) {
            return RPC_BAD_FRAME;
        }

        size_t room = m->ret_len;
        status      = m->fn.var(args, args_len, ret, &room);

        if (status == RPC_OK && room > m->ret_len) {
            status = RPC_INTERNAL;
        }

        *ret_len = (status == RPC_OK) ? room : 0;
    } else {
        /*
         * Exact both ways. Either mismatch means the ends disagree about this
         * method.
         */
        if (args_len != m->args_len) {
            return RPC_BAD_FRAME;
        }

        status   = m->fn.fixed(args, ret);
        *ret_len = (status == RPC_OK) ? m->ret_len : 0;
    }

    return status;
}

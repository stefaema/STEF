/**
 * @file rpc_dispatch.h
 * @brief Turns a namespace and a method number into a call.
 *
 * Namespaces are registered at run time, to avoid this file naming, and linking
 * against, every handler. A caller installs the tables it serves, and a test
 * installs only what it tests.
 *
 * ## Sizes in the table
 *
 * Each entry carries its payload lengths, and dispatch checks them before the
 * handler reads the first field. `sizeof` is taken where the table is defined,
 * so this file names no handler type.
 *
 * ## Fixed and variable
 *
 * A method with fixed payloads has one exact length each way. A payload ending
 * in a flexible array carries its own count, so for those @c args_len is a
 * minimum, @c ret_len a maximum, and the handler gets the real lengths.
 */

#ifndef RPC_DISPATCH_H
#define RPC_DISPATCH_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "rpc_proto.h"

/**
 * @brief A method whose payloads are both fixed.
 *
 * @param args  exactly @c args_len bytes, already checked
 * @param ret   room for @c ret_len bytes, sent only if this returns RPC_OK
 */
typedef rpc_status_t (*rpc_fixed_fn)(const void *args, void *ret);

/**
 * @brief A method with a variable-length payload on one side or both.
 *
 * @param args      at least @c args_len bytes. Checking the exact length against
 *                  the payload's own count field is the handler's job
 * @param args_len  what actually arrived
 * @param ret       room for @c ret_len bytes
 * @param ret_len   in: the room available. Out: what was used
 */
typedef rpc_status_t (*rpc_var_fn)(const void *args, size_t args_len, void *ret, size_t *ret_len);

/** @brief One method: how to call it, and how long its payloads are. */
typedef struct {
    union {
        rpc_fixed_fn fixed;
        rpc_var_fn   var;
    } fn;
    uint16_t args_len;  /**< exact, or the minimum when @c variable */
    uint16_t ret_len;   /**< exact, or the maximum when @c variable */
    bool     variable;
} rpc_method_t;

/* ── Table entries ──────────────────────────────────────────────────────── */

/*
 * Each of these takes both lengths from the handler's name, to avoid pairing one
 * method's function with another's payload.
 *
 * The suffix says which payloads exist: none on the argument side (`_GET`),
 * none on the return side (`_ACK`), or a flexible array on either (`_VAR`).
 */

#define RPC_METHOD(name) \
    { { .fixed = (name) }, sizeof(rpc_##name##_args), sizeof(rpc_##name##_ret), false }

/** @brief Takes arguments, answers with the status alone. */
#define RPC_METHOD_ACK(name) { { .fixed = (name) }, sizeof(rpc_##name##_args), 0, false }

/** @brief Variable on the argument side, answers with the status alone. */
#define RPC_METHOD_VAR_ACK(name) { { .var = (name) }, sizeof(rpc_##name##_args), 0, true }

/** @brief Takes nothing, answers with a struct. */
#define RPC_METHOD_GET(name) { { .fixed = (name) }, 0, sizeof(rpc_##name##_ret), false }

/** @brief Variable on one side or both. Lengths are the bounds. */
#define RPC_METHOD_VAR(name) \
    { { .var = (name) }, sizeof(rpc_##name##_args), sizeof(rpc_##name##_ret), true }

/**
 * @brief Takes nothing, answers with a payload ending in a flexible array.
 *
 * The bound is given explicitly, since `sizeof` stops at the flexible member.
 * Pass the base struct plus the most elements the handler can produce.
 */
#define RPC_METHOD_VAR_GET(name, max_len) { { .var = (name) }, 0, (max_len), true }

/* ── Registry ───────────────────────────────────────────────────────────── */

/**
 * @brief Installs the methods of one namespace.
 *
 * @param ns       which namespace, below @ref RPC_NS_MAX
 * @param methods  array indexed by method number. A zeroed entry is a method
 *                 the protocol names and this build does not implement
 * @param count    length of @p methods, which is the namespace's `*_COUNT`
 *
 * @return false if @p ns is out of range, @p methods is NULL, or any entry
 *         declares a payload larger than a frame can carry
 */
bool rpc_register(uint8_t ns, const rpc_method_t *methods, size_t count);

/** @brief Forgets every registration. For tests that install a fresh table. */
void rpc_reset_registry(void);

/**
 * @brief Runs the method named by @p ns and @p method.
 *
 * @param args      the request payload
 * @param args_len  its length, checked against the table before the handler
 *                  sees it
 * @param ret       where return values go, at least the table's @c ret_len
 * @param ret_len   out: how much of @p ret to send. 0 on any failing status, to
 *                  avoid sending half an answer
 *
 * @retval RPC_NO_METHOD  no such namespace, or no such method in it
 * @retval RPC_BAD_FRAME  the payload is not the length this method takes
 * @return whatever the handler returned
 */
rpc_status_t rpc_dispatch(uint8_t ns, uint8_t method, const void *args, size_t args_len, void *ret,
                          size_t *ret_len);

#endif /* RPC_DISPATCH_H */

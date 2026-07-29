/**
 * @file rpc_dispatch.h
 * @brief Turns a namespace and a method number into a call.
 *
 * The link layer knows how to get a frame off the wire and how to put one
 * back; it must not also know what any method means. This is the seam.
 *
 * Namespaces are **registered**, not compiled in. A handler that reaches a
 * TMC2209 has to know what a TMC2209 is, and this component deliberately does
 * not: it moves frames. So the composition root registers what exists, and a
 * test registers only what it is testing, without either of them having to be
 * named here.
 *
 * ## Why the table carries sizes
 *
 * A handler receives its arguments as a struct, so something has to establish
 * that the payload really is that long before the first field is touched. The
 * length lives in the table beside the function and dispatch checks it there,
 * once, for every method at once.
 *
 * `sizeof` is evaluated where the table is defined, which is in `main` where
 * the payload structs are visible. What arrives here is an integer, so this
 * component still names no type belonging to any handler.
 *
 * ## The two shapes
 *
 * Most methods take and return a fixed struct, and those are the short form:
 * one exact length in, one exact length out.
 *
 * The handful that carry a batch, a byte string or a list end in a flexible
 * array member, and their length is settled by a count inside the payload that
 * no table can see. Those get the long form, where @c args_len is a minimum,
 * @c ret_len is a maximum, and the handler is handed the real lengths.
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
 * @param args      at least @c args_len bytes. The exact length is @p args_len,
 *                  and checking it against the payload's own count field is the
 *                  handler's, since dispatch cannot see that field
 * @param args_len  what actually arrived
 * @param ret       room for @c ret_len bytes
 * @param ret_len   in: the room available. Out: what was used
 */
typedef rpc_status_t (*rpc_var_fn)(const void *args, size_t args_len,
                                   void *ret, size_t *ret_len);

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
 * Each of these derives both lengths from the handler's own name, so a table
 * entry cannot name one method's function beside another's payload. A typo is a
 * missing type rather than a wrong number.
 *
 * The suffix says which payloads exist: none on the argument side (`_GET`),
 * none on the return side (`_ACK`), or a flexible array on either (`_VAR`).
 */

#define RPC_METHOD(name) \
    { { .fixed = (name) }, sizeof(rpc_##name##_args), sizeof(rpc_##name##_ret), false }

/** @brief Takes arguments, answers with the status alone. */
#define RPC_METHOD_ACK(name) \
    { { .fixed = (name) }, sizeof(rpc_##name##_args), 0, false }

/** @brief Takes nothing, answers with a struct. */
#define RPC_METHOD_GET(name) \
    { { .fixed = (name) }, 0, sizeof(rpc_##name##_ret), false }

/** @brief Variable on one side or both. Lengths are the bounds. */
#define RPC_METHOD_VAR(name) \
    { { .var = (name) }, sizeof(rpc_##name##_args), sizeof(rpc_##name##_ret), true }

/** @brief Takes nothing, answers with something whose length varies. */
#define RPC_METHOD_VAR_GET(name) \
    { { .var = (name) }, 0, sizeof(rpc_##name##_ret), true }

/* ── Registry ───────────────────────────────────────────────────────────── */

/**
 * @brief Installs the methods of one namespace.
 *
 * @param ns       which namespace, from @ref rpc_ns_t
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
 * @param args_len  its length, which is checked against the table before the
 *                  handler sees it
 * @param ret       where return values go, at least the table's @c ret_len
 * @param ret_len   out: how much of @p ret to send. 0 on any failing status,
 *                  so a handler that gave up halfway cannot leave half an
 *                  answer in the frame
 *
 * @retval RPC_NO_METHOD  no such namespace, or no such method in it
 * @retval RPC_BAD_FRAME  the payload is not the length this method takes
 * @return whatever the handler returned
 */
rpc_status_t rpc_dispatch(uint8_t ns, uint8_t method,
                          const void *args, size_t args_len,
                          void *ret, size_t *ret_len);

#endif /* RPC_DISPATCH_H */

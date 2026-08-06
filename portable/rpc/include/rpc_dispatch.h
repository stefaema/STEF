/**
 * @file rpc_dispatch.h
 * @brief Turns a namespace and a method number into a call.
 *
 * This RPC frame names the procedure with two numbers, a namespace and an index
 * within it. Turning those into a call is the whole of this.
 *
 * Namespaces are **registered**, not compiled in. A switch over method numbers
 * would mean naming every handler here, and naming a handler means linking
 * against everything that handler reaches for. Registration keeps all of it
 * out: a caller installs the table it serves, a test installs only what it is
 * testing, and neither has to appear in this file.
 *
 * ## Why the table carries sizes
 *
 * A handler receives its arguments as a struct, so something has to establish
 * that the payload really is that long before the first field is touched. The
 * length lives in the table beside the function, and it is checked here, the
 * same way for every method.
 *
 * `sizeof` is evaluated where the table is defined, which is wherever the
 * payload structs are visible. What arrives here is an integer, so no type
 * belonging to a handler is named in this file either.
 *
 * ## The two shapes
 *
 * A method whose payloads are both fixed takes the short form: one exact
 * length in, one exact length out.
 *
 * A payload ending in a flexible array member has no length a table can hold,
 * because the count that settles it travels inside the payload. Those take the
 * long form, where @c args_len is a minimum, @c ret_len is a maximum, and the
 * handler is handed the real lengths.
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
#define RPC_METHOD_ACK(name) { { .fixed = (name) }, sizeof(rpc_##name##_args), 0, false }

/** @brief Takes nothing, answers with a struct. */
#define RPC_METHOD_GET(name) { { .fixed = (name) }, 0, sizeof(rpc_##name##_ret), false }

/** @brief Variable on one side or both. Lengths are the bounds. */
#define RPC_METHOD_VAR(name) \
    { { .var = (name) }, sizeof(rpc_##name##_args), sizeof(rpc_##name##_ret), true }

/**
 * @brief Takes nothing, answers with a payload ending in a flexible array.
 *
 * The bound is spelled out rather than taken from `sizeof`, because `sizeof`
 * stops at the flexible member and would declare a maximum too small to hold a
 * single element. Give it the full reply: the base struct plus however many
 * elements the handler can produce.
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
rpc_status_t rpc_dispatch(uint8_t ns, uint8_t method, const void *args, size_t args_len, void *ret,
                          size_t *ret_len);

#endif /* RPC_DISPATCH_H */

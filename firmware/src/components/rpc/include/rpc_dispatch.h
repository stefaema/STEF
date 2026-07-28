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
 * Handlers read arguments from @p args and write return values into @p ret.
 * Neither needs checking as it goes, since a reader that ran out and a writer
 * that overflowed both remember it. Dispatch checks once, after.
 */

#ifndef RPC_DISPATCH_H
#define RPC_DISPATCH_H

#include <stddef.h>

#include "rpc_proto.h"
#include "rpc_wire.h"

/** @brief What every method is. */
typedef rpc_status_t (*rpc_handler_fn)(rpc_reader_t *args, rpc_writer_t *ret);

/**
 * @brief Installs the methods of one namespace.
 *
 * @param ns       which namespace, from @ref rpc_ns_t
 * @param methods  array indexed by method number. A NULL entry is a method
 *                 the protocol names and this build does not implement
 * @param count    length of @p methods, which is the namespace's `*_COUNT`
 *
 * @return false if @p ns is out of range or @p methods is NULL
 */
bool rpc_register(uint8_t ns, const rpc_handler_fn *methods, size_t count);

/** @brief Forgets every registration. For tests that install a fresh table. */
void rpc_reset_registry(void);

/**
 * @brief Runs the method named by @p req.
 *
 * On any status other than RPC_OK, @p ret is rewound to @p ret_mark, so a
 * handler that failed halfway cannot leave half an answer in the frame.
 *
 * @param req       the request header, already parsed
 * @param args      positioned on the first argument
 * @param ret       positioned after the reply header
 * @param ret_mark  @p ret's length before the handler ran
 *
 * @retval RPC_NO_METHOD   no such namespace, or no such method in it
 * @retval RPC_BAD_FRAME   arguments ran out, or bytes were left over
 * @return whatever the handler returned
 */
rpc_status_t rpc_dispatch(const rpc_req_t *req, rpc_reader_t *args,
                          rpc_writer_t *ret, size_t ret_mark);

#endif /* RPC_DISPATCH_H */

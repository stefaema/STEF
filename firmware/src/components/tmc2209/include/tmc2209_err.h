/*
 * tmc2209_err.h: the component's failure vocabulary.
 *
 * A single call like tmc2209_read can fail at three different depths: the
 * port never delivered the bytes, the datagram came back malformed, or the
 * device disagreed with what the cache believed. The caller gets one return
 * value and still has to tell those apart, because the right response differs:
 * a CRC error is worth retrying, a register mismatch means a second driver is
 * answering and retrying will not help.
 *
 * So the codes are one flat enum spanning every layer, and it lives here
 * rather than in any one layer's header. tmc2209_port.h would be the wrong
 * home: it names only the transport, while these codes also describe framing
 * and cache state.
 */

#ifndef TMC2209_ERR_H
#define TMC2209_ERR_H

typedef enum {
    TMC2209_OK = 0,
    TMC2209_ERR_ARG,          /**< caller passed something impossible */
    TMC2209_ERR_TIMEOUT,      /**< port did not deliver the bytes in time */
    TMC2209_ERR_IO,           /**< port failed for its own reasons */
    TMC2209_ERR_ECHO,         /**< what came back is not what we sent: collision or jammed line */
    TMC2209_ERR_SYNC,         /**< reply sync byte or master address wrong */
    TMC2209_ERR_CRC,          /**< CRC error */
    TMC2209_ERR_REG,          /**< reply is for a register we did not ask about */
    TMC2209_ERR_NO_ACK,       /**< IFCNT did not advance: the write never landed */
    TMC2209_ERR_ACCESS,       /**< the register access policy does not permit this operation */
    TMC2209_ERR_INVALID_SLOT, /**< the cache holds no usable value for that register,
                                   because none was ever written or because the driver
                                   reset. Not a complaint about the argument */
    TMC2209_ERR_MISMATCH,     /**< the device disagrees with the cache */
} tmc2209_err_t;

/* Never NULL, including for a value outside the enum. */
const char *tmc2209_strerror(tmc2209_err_t err);

#endif /* TMC2209_ERR_H */

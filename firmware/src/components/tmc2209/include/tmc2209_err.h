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
    /* Two directions, two codes. A single timeout would leave the caller unable
       to tell its own transmit path from a driver that said nothing, which are
       opposite ends of the cable. */
    TMC2209_ERR_TX_TIMEOUT,   /**< port accepted fewer bytes than it was given */
    TMC2209_ERR_RX_TIMEOUT,   /**< port delivered fewer bytes than were asked for */
    TMC2209_ERR_IO,           /**< port failed for its own reasons */
    TMC2209_ERR_ECHO,         /**< what came back is not what we sent: collision or jammed line */
    TMC2209_ERR_SYNC,         /**< reply sync byte or master address wrong */
    TMC2209_ERR_CRC,          /**< CRC error */
    TMC2209_ERR_REG,          /**< reply is for a register we did not ask about */
    TMC2209_ERR_NO_ACK,       /**< IFCNT did not advance enough: the write didn't land right */
    TMC2209_ERR_ACCESS,       /**< the register access policy does not permit this operation,
                                   or the line named is one the driver drives rather than reads */
    TMC2209_ERR_UNWIRED,      /**< the line is not connected on this board */
    TMC2209_ERR_INVALID_SLOT, /**< the cache holds an invalid value for that register,
                                   because none was ever written or because the driver
                                   may have a different value than the cached one. */
    TMC2209_ERR_MISMATCH,     /**< the device disagrees with the cache */
} tmc2209_err_t;

/* Never NULL, including for a value outside the enum. */
const char *tmc2209_strerror(tmc2209_err_t err);

#endif /* TMC2209_ERR_H */

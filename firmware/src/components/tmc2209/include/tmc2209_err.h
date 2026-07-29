/**
 * @file tmc2209_err.h
 * @brief The component's failure vocabulary.
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

/** @brief Every way a call in this component can fail. */
typedef enum {
    TMC2209_OK = 0,
    TMC2209_ERR_ARG,          /**< caller passed something impossible */
    TMC2209_ERR_TX_TIMEOUT,   /**< Port accepted fewer bytes than it was given. */
    TMC2209_ERR_RX_TIMEOUT,   /**< port delivered fewer bytes than were asked for */
    TMC2209_ERR_IO,           /**< port failed for its own reasons */
    TMC2209_ERR_ECHO,         /**< what came back is not what we sent: collision or jammed line */
    TMC2209_ERR_PREAMBLE,     /**< first two bytes of a reply datagram wrong: SYNC and MASTER_ADDR */
    TMC2209_ERR_CRC,          /**< CRC error */
    TMC2209_ERR_REG,          /**< reply is for a register we did not ask about */
    TMC2209_ERR_NO_ACK,       /**< IFCNT did not advance enough: the write didn't land right */
    TMC2209_ERR_ACCESS,       /**< the register/line access policy does not permit this operation */
    TMC2209_ERR_NO_BACKEND,   /**< nothing is attached to carry out this call */
    TMC2209_ERR_UNWIRED,      /**< the line is not connected on this board */
    TMC2209_ERR_INVALID_SLOT, /**< the cache holds an invalid value for that register */
    TMC2209_ERR_MISMATCH,     /**< the device disagrees with the cache */
    TMC2209_ERR_BUSY,         /**< A run is in flight and this call would disturb it. **/
    TMC2209_ERR_IDLE,         /**< no run is in flight and this call needs one */
    TMC2209_ERR_UNREAD,       /**< the last run's pulse count was ignored and another run was requested */
    TMC2209_ERR_RATE,         /**< a rate beyond what this stepgen can emit. */
} tmc2209_err_t;

/**
 * @brief Names a error code, for a log line or an operator.
 *
 * @param err  any value, in the enum or not
 *
 * @return a static string, never NULL, so it drops straight into a %s
 */
const char *tmc2209_strerror(tmc2209_err_t err);

#endif /* TMC2209_ERR_H */

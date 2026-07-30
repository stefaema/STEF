/**
 * @file rpc_link.h
 * @brief Carries frames over the native USB port, and nothing else does.
 *
 * One cable does everything: flashing, JTAG, and this. So `ESP_LOGI` cannot
 * also go to stdout, because raw text between frames is exactly what a framer
 * must not receive. Starting the link redirects the log stream into it, and
 * from that moment a log is a frame like any other.
 *
 * See firmware/docs/top-bottom-assessment.md, "How RPC Works".
 */

#ifndef RPC_LINK_H
#define RPC_LINK_H

#include "esp_err.h"

/**
 * @brief Installs the USB driver, takes over logging, and starts serving.
 *
 * Returns once both tasks are running. Requests are answered from then on,
 * with no further involvement from the caller.
 *
 * @retval ESP_OK
 * @retval ESP_ERR_INVALID_STATE  already started
 * @retval ESP_ERR_NO_MEM         queue or task would not fit
 * @return whatever the USB driver install returned
 */
esp_err_t rpc_link_start(void);

#endif /* RPC_LINK_H */

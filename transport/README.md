# Transport

This part of the project implements the PC-side client of the film transport. It speaks the
RPC protocol to the firmware over USB, and exposes the transport to the orchestrator as one
of its three subsystems.

The contract it speaks is `shared/fw_api`, which carries both the C declaration the firmware
compiles and the ctypes view this module imports.

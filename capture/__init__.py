"""The camera, over the network.

One Canon body reached by the CCAPI protocol it serves over HTTP, which is the
only proprietary part of this machine and the one part nobody here wrote.
"""

from capture.capture import camera, state

__all__ = ["camera", "state"]

"""The camera, over the network.

One Canon body reached by the CCAPI protocol it serves over HTTP, which is the
only proprietary part of this machine and the one part nobody here wrote.
"""

from capture.subsystem import Capture

SUBSYSTEM = Capture

__all__ = ["SUBSYSTEM", "Capture"]

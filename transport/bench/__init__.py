"""What the operator does to the transport when it is out of service.

Importing the subsystem module is what puts `@subsystem` in the registry, and a
declaration in here finds its owner by looking for one. Walking this package
imports this file first, so doing it here is what lets any module below declare
without importing the subsystem for itself.
"""

from transport import transport  # noqa: F401

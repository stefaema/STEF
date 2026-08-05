GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def heading(text: str) -> None:
    """Print the line that introduces the checks below it."""
    print(f"{DIM}{text}{OFF}")


def hint(command: str) -> None:
    """Print the command that fixes what just failed."""
    print(f"  {DIM}fix with: {command}{OFF}")


def report(label: str, ok: bool, note: str = "") -> bool:
    """Print the check's verdict and hand it back, so callers can chain on it."""
    mark = f"{GREEN}ok{OFF}" if ok else f"{RED}FAIL{OFF}"
    tail = f" {DIM}{note}{OFF}" if note else ""
    print(f"  {mark:<16} {label}{tail}")
    return ok


def skip(label: str, why: str) -> bool:
    """Print why the check did not run, returning True so it cannot fail the run."""
    print(f"  {YELLOW}skip{OFF}{'':<12} {label} {DIM}{why}{OFF}")
    return True

GREEN, RED, YELLOW, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def heading(text: str) -> None:
    print(f"{DIM}{text}{OFF}")


def report(label: str, ok: bool, note: str = "") -> bool:
    mark = f"{GREEN}ok{OFF}" if ok else f"{RED}FAIL{OFF}"
    tail = f" {DIM}{note}{OFF}" if note else ""
    print(f"  {mark:<16} {label}{tail}")
    return ok


def skip(label: str, why: str) -> bool:
    print(f"  {YELLOW}skip{OFF}{'':<12} {label} {DIM}{why}{OFF}")
    return True

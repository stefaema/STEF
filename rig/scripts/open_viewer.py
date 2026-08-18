from discovery import collect


def main() -> None:
    shown = collect()
    if not shown:
        print("no module under src/ defines build() or sample()")
        return

    from yacv_server import show

    for name in shown:
        print(name)
    show(*shown.values(), names=list(shown.keys()))  # pyright: ignore[reportArgumentType]


if __name__ == "__main__":
    main()

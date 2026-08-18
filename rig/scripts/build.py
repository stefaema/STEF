from discovery import BUILDS, collect


def main() -> None:
    parts = collect()
    if not parts:
        print("no module under src/ defines build() or sample()")
        return

    from build123d import Mesher, export_stl

    for name, part in parts.items():
        stl = BUILDS / f"{name}.stl"
        stl.parent.mkdir(parents=True, exist_ok=True)
        export_stl(part, str(stl))

        mesher = Mesher()
        mesher.add_shape(part)
        three_mf = BUILDS / f"{name}.3mf"
        mesher.write(str(three_mf))

        print(stl.relative_to(BUILDS.parent))


if __name__ == "__main__":
    main()

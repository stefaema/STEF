# The tmc2209 library

> Status: empty.
> Language: English.
> Thesis: Desarrollo de Firmware.
> Source material: `design.md` §2, §3, §5 and §7.

Scope: The register cache, the three API families, transport policy, inherited defects.

Cutting rule, the complement of the one in `../appendix/tmc2209.md`: everything
here is a decision **we** made about the part. The `VOLATILE` / `OWNED` /
`CONSTANT` classification belongs here and not in the appendix, because it is our
policy rather than a property of the silicon.

#!/usr/bin/env python3
"""Interactive bench console for the firmware's RPC link.

Pick a namespace, pick a method, fill in the arguments, send, read the reply.

Nothing about the protocol is written down here. The namespaces, the method
numbers, the payload layouts and the status names are all parsed out of
`rpc_proto.h` and `rpc_api.h` at start-up, which are the same two files the
firmware compiles. That is the whole point: a method number or a struct field
that changes on one side cannot silently disagree with the other, because there
is only one declaration and this script reads it.

The parser leans on the layout rules those headers already promise: fixed-width
types, padding declared by hand rather than left to a compiler, and every struct
asserting its own size with RPC_WIRE_SIZE. That last one is also the parser's
test: every computed layout is checked against the declared size, and a
mismatch is a hard error rather than a frame that goes out wrong.

Usage:
    nix develop --command python3 scripts/rpc_console.py
    nix develop --command python3 scripts/rpc_console.py --port /dev/ttyACM0 -v
"""

import argparse
import os
import re
import struct
import sys
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    sys.exit("needs pyserial: run inside `nix develop`")


HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
PROTO_H = os.path.join(ROOT, "rpc", "include", "rpc_proto.h")
API_H = os.path.join(ROOT, "shared", "rpc_api", "include", "rpc_api.h")

# The method enums are named after their namespace, except this one. `rpc_ns_t`
# says PASSTHROUGH and the methods say PT.
NS_PREFIX_ALIAS = {"passthrough": "pt"}

SCALARS = {
    "uint8_t": ("B", 1),
    "int8_t": ("b", 1),
    "uint16_t": ("H", 2),
    "int16_t": ("h", 2),
    "uint32_t": ("I", 4),
    "int32_t": ("i", 4),
    "char": ("c", 1),
}


# ── Reading the headers ──────────────────────────────────────────────────────


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


class Api:
    """Everything the two headers declare, as Python data."""

    def __init__(self, sources):
        self.consts = {}
        self.enums = {}          # typedef name -> {member: value}
        self.anon_enums = []     # [{member: value}]
        self.structs = {}        # name -> [(field, ctype, count_or_None)]
        self.declared_size = {}  # name -> what RPC_WIRE_SIZE claims
        self.aliases = {}        # new name -> existing name

        for path in sources:
            with open(path) as fh:
                self._scan(strip_comments(fh.read()))

    def _value(self, expr):
        expr = re.sub(r"\b(\d+)[uUlL]+\b", r"\1", expr).strip()
        try:
            return int(eval(expr, {"__builtins__": {}}, dict(self.consts)))
        except Exception:
            return None

    def _scan(self, text):
        for name, body in re.findall(r"^\s*#define\s+(\w+)\s+([^\n]+)$", text, re.M):
            value = self._value(body)
            if value is not None:
                self.consts[name] = value

        for body, tag in re.findall(r"enum\s*\{(.*?)\}\s*(\w*)\s*;", text, re.S):
            members, nxt = {}, 0
            for entry in body.split(","):
                entry = entry.strip()
                if not entry:
                    continue
                if "=" in entry:
                    key, expr = entry.split("=", 1)
                    value = self._value(expr)
                    if value is None:
                        continue
                else:
                    key, value = entry, nxt
                members[key.strip()] = value
                self.consts[key.strip()] = value
                nxt = value + 1
            if tag:
                self.enums[tag] = members
            else:
                self.anon_enums.append(members)

        for body, name in re.findall(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", text, re.S):
            self.structs[name] = self._fields(body)

        for old, new in re.findall(r"typedef\s+(\w+)\s+(\w+)\s*;", text):
            if old in ("struct", "enum", "unsigned", "signed"):
                continue
            self.aliases[new] = old

        for name, size in re.findall(r"RPC_WIRE_SIZE\s*\(\s*(\w+)\s*,\s*([^)]+)\)", text):
            value = self._value(size)
            if value is not None:
                self.declared_size[name] = value

    def _fields(self, body):
        fields = []
        for line in body.split(";"):
            line = " ".join(line.split())
            m = re.match(r"^(\w+)\s+([\w\s,\[\]]+)$", line)
            if not m:
                continue
            ctype, rest = m.group(1), m.group(2)
            for decl in rest.split(","):
                decl = decl.strip()
                arr = re.match(r"^(\w+)\s*\[\s*([^\]]*)\s*\]$", decl)
                if arr:
                    dim = arr.group(2).strip()
                    count = self._value(dim) if dim else 0  # 0 = flexible
                    fields.append((arr.group(1), ctype, count))
                elif re.match(r"^\w+$", decl):
                    fields.append((decl, ctype, None))
        return fields

    def resolve(self, name):
        seen = set()
        while name in self.aliases and name not in self.structs and name not in seen:
            seen.add(name)
            name = self.aliases[name]
        return name


# ── Turning a struct into a wire layout ──────────────────────────────────────


class Field:
    def __init__(self, name, ctype, count, offset, size, align, nested=None):
        self.name, self.ctype, self.count = name, ctype, count
        self.offset, self.size, self.align = offset, size, align
        self.nested = nested

    @property
    def is_pad(self):
        return self.name.startswith("_")

    @property
    def is_flexible(self):
        return self.count == 0


class Layout:
    """A struct's fields at their wire offsets, checked against RPC_WIRE_SIZE."""

    def __init__(self, api, name):
        self.api = api
        self.name = api.resolve(name)
        if self.name not in api.structs:
            raise KeyError(name)

        self.fields, self.flexible = [], None
        offset = align = 1

        for fname, ctype, count in api.structs[self.name]:
            nested = None
            if ctype in SCALARS:
                unit = SCALARS[ctype][1]
            else:
                nested = Layout(api, ctype)
                unit = nested.align
            offset = (offset + unit - 1) // unit * unit if self.fields else 0
            align = max(align, unit)

            width = unit if nested is None else nested.size
            n = 1 if count is None else count
            field = Field(fname, ctype, count, offset, width * n, unit, nested)
            if count == 0:
                self.flexible = field
            else:
                self.fields.append(field)
                offset += width * n

        self.align = align
        self.size = (offset + align - 1) // align * align

        declared = api.declared_size.get(self.name)
        if declared is not None and declared != self.size:
            raise ValueError(
                f"{self.name}: computed {self.size} bytes, header asserts {declared}. "
                "The parser and the protocol disagree; do not trust this script."
            )

    def unit_size(self, field):
        return field.nested.size if field.nested else SCALARS[field.ctype][1]

    # -- encode ---------------------------------------------------------------

    def pack(self, values, tail=None):
        buf = bytearray(self.size)
        for f in self.fields:
            if f.is_pad:
                continue
            self._put(buf, f, values[f.name])
        if self.flexible and tail:
            for item in tail:
                if self.flexible.nested:
                    buf += self.flexible.nested.pack(item)
                else:
                    buf += struct.pack("<" + SCALARS[self.flexible.ctype][0], item)
        return bytes(buf)

    def _put(self, buf, f, value):
        code = SCALARS[f.ctype][0] if f.nested is None else None
        if f.ctype == "char" and f.count:
            raw = str(value).encode()[: f.count - 1]
            buf[f.offset : f.offset + f.count] = raw.ljust(f.count, b"\0")
        elif f.count:
            for i, item in enumerate(value):
                struct.pack_into("<" + code, buf, f.offset + i * f.align, item)
        else:
            struct.pack_into("<" + code, buf, f.offset, value)

    # -- decode ---------------------------------------------------------------

    def unpack(self, data):
        out = {}
        for f in self.fields:
            if f.is_pad:
                continue
            out[f.name] = self._get(data, f)
        if self.flexible:
            unit = self.unit_size(self.flexible)
            rest, items = data[self.size :], []
            for off in range(0, len(rest) - unit + 1, unit):
                chunk = rest[off : off + unit]
                items.append(
                    self.flexible.nested.unpack(chunk)
                    if self.flexible.nested
                    else struct.unpack("<" + SCALARS[self.flexible.ctype][0], chunk)[0]
                )
            out[self.flexible.name] = items
        return out

    def _get(self, data, f):
        if f.nested:
            unit = f.nested.size
            if f.count:
                return [
                    f.nested.unpack(data[f.offset + i * unit : f.offset + (i + 1) * unit])
                    for i in range(f.count)
                ]
            return f.nested.unpack(data[f.offset : f.offset + unit])

        code = SCALARS[f.ctype][0]
        if f.ctype == "char" and f.count:
            return data[f.offset : f.offset + f.count].split(b"\0")[0].decode(errors="replace")
        if f.count:
            return list(struct.unpack_from("<" + code * f.count, data, f.offset))
        return struct.unpack_from("<" + code, data, f.offset)[0]


# ── The wire ─────────────────────────────────────────────────────────────────


def crc16_ccitt(data):
    """Mirrors crc16.c: poly 0x1021, init 0xFFFF, no reflection, no final xor."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def cobs_encode(src):
    out, code_at, code = bytearray([0]), 0, 1
    for byte in src:
        if byte == 0:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
            continue
        out.append(byte)
        code += 1
        if code == 0xFF:
            out[code_at] = code
            code_at, code = len(out), 1
            out.append(0)
    out[code_at] = code
    return bytes(out)


def cobs_decode(src):
    out, i = bytearray(), 0
    while i < len(src):
        code = src[i]
        i += 1
        if code == 0 or i + code - 1 > len(src):
            return None
        out += src[i : i + code - 1]
        i += code - 1
        if code != 0xFF and i < len(src):
            out.append(0)
    return bytes(out)


class Link:
    def __init__(self, api, port, verbose=False):
        self.api = api
        self.verbose = verbose
        self.port = serial.Serial(port, 115200, timeout=0.05)
        self.port.reset_input_buffer()
        self.next_id = 1
        self.hdr_len = api.consts["RPC_HDR_LEN"]

        self.req = Layout(api, "rpc_req_hdr_t")
        self.rep = Layout(api, "rpc_rep_hdr_t")
        self.log = Layout(api, "rpc_log_hdr_t")

    def send(self, ns, method, payload=b""):
        rid = self.next_id
        self.next_id = (self.next_id + 1) & 0xFFFF

        hdr = self.req.pack(
            {"type": self.api.consts["RPC_FRAME_REQ"], "ns": ns, "method": method, "id": rid}
        )
        body = hdr + payload
        frame = body + struct.pack("<H", crc16_ccitt(body))
        wire = cobs_encode(frame) + b"\0"

        if self.verbose:
            print(f"  tx {len(wire)}B: {wire.hex(' ')}")
        self.port.write(wire)
        return rid

    def _frames(self, deadline):
        run = bytearray()
        while time.monotonic() < deadline:
            chunk = self.port.read(256)
            if not chunk:
                continue
            for byte in chunk:
                if byte != 0:
                    run.append(byte)
                    continue
                if run:
                    decoded = cobs_decode(bytes(run))
                    run.clear()
                    if decoded and len(decoded) >= self.hdr_len + 2:
                        body = decoded[:-2]
                        want = struct.unpack("<H", decoded[-2:])[0]
                        if crc16_ccitt(body) == want:
                            yield decoded, body
                        elif self.verbose:
                            print("  rx: CRC mismatch, dropped")
                run.clear()

    def await_reply(self, rid, timeout=2.0):
        deadline = time.monotonic() + timeout
        for decoded, body in self._frames(deadline):
            if self.verbose:
                print(f"  rx {len(decoded)}B: {decoded.hex(' ')}")
            kind = body[0]
            if kind == self.api.consts["RPC_FRAME_LOG"]:
                head = self.log.unpack(body[: self.hdr_len])
                text = body[self.hdr_len :].decode(errors="replace")
                print(f"  [log {head['level']} @{head['uptime_ms']}ms] {text}")
                continue
            if kind != self.api.consts["RPC_FRAME_REP"]:
                continue
            head = self.rep.unpack(body[: self.hdr_len])
            if head["id"] != rid:
                print(f"  (reply for id {head['id']}, expected {rid}; ignored)")
                continue
            return head, body[self.hdr_len :]
        return None, None


# ── Menu ─────────────────────────────────────────────────────────────────────


def status_names(api):
    names = {}
    for members in api.anon_enums:
        for key, value in members.items():
            if key.endswith("_LAST"):
                continue
            names.setdefault(value, key)
    return names


def namespaces(api):
    """Namespaces from rpc_ns_t that actually have a method enum behind them."""
    found = []
    for key, value in sorted(api.enums["rpc_ns_t"].items(), key=lambda kv: kv[1]):
        if key.endswith("_COUNT"):
            continue
        short = key[len("RPC_NS_") :].lower()
        prefix = NS_PREFIX_ALIAS.get(short, short)
        enum = api.enums.get(f"rpc_{prefix}_method_t")
        if enum:
            found.append((short, prefix, value, enum))
    return found


def methods(enum, prefix):
    out = []
    for key, value in sorted(enum.items(), key=lambda kv: kv[1]):
        if key.endswith("_COUNT"):
            continue
        out.append((key[len(f"RPC_{prefix.upper()}_") :].lower(), value, key))
    return out


def ask(prompt, default=None):
    suffix = f" [{default}]" if default is not None else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default is not None:
            return str(default)
        if raw:
            return raw


def ask_int(prompt, default=None):
    while True:
        raw = ask(prompt, default)
        try:
            return int(raw, 0)
        except ValueError:
            print("  necesito un entero (0x.. sirve)")


def collect(layout):
    """Prompt for every field the caller owns. Padding is never asked about."""
    values, tail = {}, []
    for f in layout.fields:
        if f.is_pad:
            continue
        if f.ctype == "char" and f.count:
            values[f.name] = ask(f"  {f.name} (str[{f.count}])", "")
        elif f.count:
            items = ask(f"  {f.name} ({f.ctype}[{f.count}], separados por espacio)", "")
            got = [int(x, 0) for x in items.split()]
            values[f.name] = (got + [0] * f.count)[: f.count]
        else:
            values[f.name] = ask_int(f"  {f.name} ({f.ctype})", 0)

    flex = layout.flexible
    if flex:
        n = ask_int(f"  cuántos {flex.name}[] ({flex.ctype})", 0)
        for i in range(n):
            if flex.nested:
                print(f"  -- {flex.name}[{i}]")
                tail.append(collect(flex.nested)[0])
            else:
                tail.append(ask_int(f"  {flex.name}[{i}]", 0))
        for name in ("count", "reply_len"):
            if name in values and values[name] == 0 and n:
                values[name] = n
    return values, tail


def show(value, indent="    "):
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                print(f"{indent}{k}:")
                show(v, indent + "  ")
            else:
                print(f"{indent}{k} = {v}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, dict):
                print(f"{indent}[{i}]")
                show(item, indent + "  ")
            else:
                print(f"{indent}[{i}] = {item}")
    else:
        print(f"{indent}{value}")


def pick(title, options):
    print(f"\n{title}")
    for i, label in enumerate(options):
        print(f"  {i:2d}) {label}")
    print("   q) salir     b) volver")
    while True:
        raw = input("> ").strip().lower()
        if raw in ("q", "b"):
            return raw
        if raw.isdigit() and int(raw) < len(options):
            return int(raw)
        print("  opción inválida")


def find_port():
    for p in list_ports.comports():
        if p.vid == 0x303A:
            return p.device
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", help="serial port (autodetects Espressif native USB)")
    ap.add_argument("-v", "--verbose", action="store_true", help="show frames in hex")
    ap.add_argument("--timeout", type=float, default=2.0, help="reply timeout, seconds")
    args = ap.parse_args()

    api = Api([PROTO_H, API_H])
    statuses = status_names(api)
    spaces = namespaces(api)

    print(f"rpc_api.h: protocolo v{api.consts['RPC_PROTOCOL_VERSION']}, "
          f"{len(spaces)} namespaces servidos, {len(api.structs)} structs leídos")
    missing = [
        k[len("RPC_NS_"):].lower()
        for k in api.enums["rpc_ns_t"]
        if not k.endswith("_COUNT")
        and k[len("RPC_NS_"):].lower() not in [s[0] for s in spaces]
    ]
    if missing:
        print(f"declarados sin tabla de métodos, omitidos: {', '.join(missing)}")

    port = args.port or find_port()
    if not port:
        sys.exit("no encontré la placa; pasá --port")
    print(f"puerto: {port}\n")

    link = Link(api, port, args.verbose)

    while True:
        choice = pick("namespace:", [f"{s[0]:<12} (ns {s[2]})" for s in spaces])
        if choice == "q":
            return
        if choice == "b":
            continue
        short, prefix, ns, enum = spaces[choice]

        while True:
            ms = methods(enum, prefix)
            choice = pick(f"{short}.method:", [f"{m[0]:<18} ({m[1]})" for m in ms])
            if choice == "q":
                return
            if choice == "b":
                break
            mname, mnum, _ = ms[choice]

            payload, tail = b"", None
            try:
                layout = Layout(api, f"rpc_{prefix}_{mname}_args")
            except (KeyError, ValueError) as exc:
                if isinstance(exc, ValueError):
                    print(f"  !! {exc}")
                    continue
                layout = None

            if layout:
                print(f"\n{short}.{mname} argumentos ({layout.name}):")
                values, tail = collect(layout)
                payload = layout.pack(values, tail)
            else:
                print(f"\n{short}.{mname} no lleva argumentos")

            rid = link.send(ns, mnum, payload)
            head, body = link.await_reply(rid, args.timeout)
            if head is None:
                print("  !! sin respuesta (timeout)")
                continue

            code = head["status"]
            label = statuses.get(code, "?")
            print(f"\n  status = {code} ({label}), {len(body)} bytes de payload")

            if not body:
                continue
            try:
                ret = Layout(api, f"rpc_{prefix}_{mname}_ret")
            except (KeyError, ValueError):
                print(f"    (sin struct de retorno declarado) {body.hex(' ')}")
                continue
            try:
                show(ret.unpack(body))
            except Exception as exc:
                print(f"    no pude decodificar con {ret.name}: {exc}")
                print(f"    crudo: {body.hex(' ')}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()

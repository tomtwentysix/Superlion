"""Parser and writer for Valve's text KeyValues format (.vdf and .acf files)."""

_UNESCAPE = {"n": "\n", "t": "\t", "\\": "\\", '"': '"'}
# Steam writes newlines and tabs inside strings literally; only these are escaped.
_ESCAPE = {"\\": "\\\\", '"': '\\"'}


def _tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif c in "{}":
            yield c
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n and text[i + 1] in _UNESCAPE:
                    i += 1
                    buf.append(_UNESCAPE[text[i]])
                else:
                    buf.append(text[i])
                i += 1
            i += 1
            yield ("str", "".join(buf))
        else:
            # Unquoted token; runs until whitespace or a brace.
            start = i
            while i < n and not text[i].isspace() and text[i] not in '{}"':
                i += 1
            yield ("str", text[start:i])


def loads(text):
    """Parse KeyValues text into nested dictionaries of strings."""
    root = {}
    stack = [root]
    key = None
    for tok in _tokenize(text):
        if tok == "{":
            child = {}
            stack[-1][key if key is not None else ""] = child
            stack.append(child)
            key = None
        elif tok == "}":
            if len(stack) > 1:
                stack.pop()
            key = None
        elif key is None:
            key = tok[1]
        else:
            stack[-1][key] = tok[1]
            key = None
    return root


def load(path):
    with open(path, encoding="utf-8", errors="surrogateescape") as fh:
        return loads(fh.read())


def _quote(s):
    return '"' + "".join(_ESCAPE.get(c, c) for c in s) + '"'


def dumps(data, depth=0):
    """Serialise nested dictionaries in the layout the Steam client writes."""
    out = []
    pad = "\t" * depth
    for key, value in data.items():
        if isinstance(value, dict):
            out.append(f"{pad}{_quote(key)}\n{pad}{{\n")
            out.append(dumps(value, depth + 1))
            out.append(f"{pad}}}\n")
        else:
            out.append(f"{pad}{_quote(key)}\t\t{_quote(value)}\n")
    return "".join(out)


def dump(data, path):
    with open(path, "w", encoding="utf-8", errors="surrogateescape") as fh:
        fh.write(dumps(data))


def get_path(data, *keys):
    """Follow keys case-insensitively, as the Steam client does; None if absent."""
    node = data
    for key in keys:
        if not isinstance(node, dict):
            return None
        match = next((k for k in node if k.lower() == key.lower()), None)
        if match is None:
            return None
        node = node[match]
    return node


def ensure_path(data, *keys):
    """Like get_path, but creates missing dictionaries along the way."""
    node = data
    for key in keys:
        match = next((k for k in node if k.lower() == key.lower()), None)
        if match is None or not isinstance(node[match], dict):
            match = match or key
            node[match] = {}
        node = node[match]
    return node


_B_MAP, _B_STRING, _B_INT32, _B_FLOAT, _B_UINT64, _B_END = 0, 1, 2, 3, 7, 8


class UInt64(int):
    """Marks a 64-bit value so it is written back with its original type."""


class Float32(float):
    """Marks a 32-bit float so it is written back with its original type."""


def loads_binary(data):
    """Parse Steam's binary KeyValues into nested dictionaries.

    Strings become str, 32-bit integers int (read unsigned, as app IDs are),
    and the rarer 64-bit and float values keep marker types for writing back.
    """
    import struct

    pos = 0

    def read_cstring():
        nonlocal pos
        end = data.index(b"\0", pos)
        text = data[pos:end].decode("utf-8", "surrogateescape")
        pos = end + 1
        return text

    def read_map():
        nonlocal pos
        node = {}
        while True:
            kind = data[pos]
            pos += 1
            if kind == _B_END:
                return node
            key = read_cstring()
            if kind == _B_MAP:
                node[key] = read_map()
            elif kind == _B_STRING:
                node[key] = read_cstring()
            elif kind == _B_INT32:
                node[key] = struct.unpack_from("<I", data, pos)[0]
                pos += 4
            elif kind == _B_FLOAT:
                node[key] = Float32(struct.unpack_from("<f", data, pos)[0])
                pos += 4
            elif kind == _B_UINT64:
                node[key] = UInt64(struct.unpack_from("<Q", data, pos)[0])
                pos += 8
            else:
                raise ValueError(f"Unknown binary KeyValues type {kind} at offset {pos - 1}")

    root = read_map()
    return root


def dumps_binary(node):
    import struct

    out = bytearray()
    for key, value in node.items():
        encoded_key = key.encode("utf-8", "surrogateescape") + b"\0"
        if isinstance(value, dict):
            out += bytes([_B_MAP]) + encoded_key + dumps_binary(value)
        elif isinstance(value, str):
            out += bytes([_B_STRING]) + encoded_key + value.encode("utf-8", "surrogateescape") + b"\0"
        elif isinstance(value, UInt64):
            out += bytes([_B_UINT64]) + encoded_key + struct.pack("<Q", value)
        elif isinstance(value, Float32):
            out += bytes([_B_FLOAT]) + encoded_key + struct.pack("<f", value)
        else:
            out += bytes([_B_INT32]) + encoded_key + struct.pack("<I", value & 0xFFFFFFFF)
    out.append(_B_END)
    return bytes(out)


def load_binary(path):
    with open(path, "rb") as fh:
        return loads_binary(fh.read())

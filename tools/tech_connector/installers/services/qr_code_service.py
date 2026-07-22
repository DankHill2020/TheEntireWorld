"""Small dependency-free QR SVG generator for mobile pairing URLs.

This implements byte-mode QR codes for versions 1-10 with error correction L.
It is intentionally scoped to the mobile pairing URL use case.
"""

from __future__ import annotations

from dataclasses import dataclass


CAPACITY_L_BYTE = {
    1: (19, 7),
    2: (34, 10),
    3: (55, 15),
    4: (80, 20),
    5: (108, 26),
    6: (136, 36),
    7: (156, 40),
    8: (194, 48),
    9: (232, 60),
    10: (274, 72),
}

FORMAT_BITS_L = {
    0: 0b111011111000100,
    1: 0b111001011110011,
    2: 0b111110110101010,
    3: 0b111100010011101,
    4: 0b110011000101111,
    5: 0b110001100011000,
    6: 0b110110001000001,
    7: 0b110100101110110,
}


@dataclass
class QRMatrix:
    modules: list[list[bool | None]]
    reserved: list[list[bool]]

    @property
    def size(self) -> int:
        return len(self.modules)


def qr_svg(text: str, *, border: int = 4, scale: int = 8) -> str:
    matrix = qr_matrix(text)
    size = matrix.size
    view_size = (size + border * 2) * scale
    rects = []
    for y, row in enumerate(matrix.modules):
        for x, value in enumerate(row):
            if value:
                rects.append(
                    f'<rect x="{(x + border) * scale}" y="{(y + border) * scale}" width="{scale}" height="{scale}"/>'
                )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_size} {view_size}" '
        f'width="{view_size}" height="{view_size}" shape-rendering="crispEdges">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>'
        f'<g fill="#000000">{"".join(rects)}</g></svg>'
    )


def qr_matrix(text: str) -> QRMatrix:
    data = text.encode("utf-8")
    version = _choose_version(len(data))
    data_capacity, ecc_count = CAPACITY_L_BYTE[version]
    codewords = _data_codewords(data, data_capacity)
    ecc = _reed_solomon_ecc(codewords, ecc_count)
    bits = _bits_from_codewords(codewords + ecc)
    matrix = _base_matrix(version)
    _place_data(matrix, bits)
    best = None
    best_score = None
    for mask in range(8):
        candidate = _copy_matrix(matrix)
        _apply_mask(candidate, mask)
        _add_format_bits(candidate, mask)
        score = _penalty(candidate.modules)
        if best is None or score < best_score:
            best = candidate
            best_score = score
    return best


def _choose_version(byte_len: int) -> int:
    for version, (capacity, _ecc) in CAPACITY_L_BYTE.items():
        if byte_len <= capacity - 2:
            return version
    raise ValueError("QR pairing URL is too long for built-in QR generator")


def _data_codewords(data: bytes, capacity: int) -> list[int]:
    bits = [0, 1, 0, 0]  # byte mode
    bits.extend(_int_bits(len(data), 8))
    for byte in data:
        bits.extend(_int_bits(byte, 8))
    max_bits = capacity * 8
    bits.extend([0] * min(4, max_bits - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    codewords = [_bits_to_int(bits[i:i + 8]) for i in range(0, len(bits), 8)]
    pads = [0xEC, 0x11]
    pad_index = 0
    while len(codewords) < capacity:
        codewords.append(pads[pad_index % 2])
        pad_index += 1
    return codewords


def _int_bits(value: int, width: int) -> list[int]:
    return [(value >> shift) & 1 for shift in range(width - 1, -1, -1)]


def _bits_to_int(bits: list[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def _bits_from_codewords(codewords: list[int]) -> list[int]:
    bits = []
    for codeword in codewords:
        bits.extend(_int_bits(codeword, 8))
    return bits


def _gf_mul(x: int, y: int) -> int:
    result = 0
    while y:
        if y & 1:
            result ^= x
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
        y >>= 1
    return result


def _gf_pow(x: int, power: int) -> int:
    result = 1
    for _ in range(power):
        result = _gf_mul(result, x)
    return result


def _rs_generator(degree: int) -> list[int]:
    poly = [1]
    for i in range(degree):
        factor = [1, _gf_pow(2, i)]
        poly = [_gf_poly_coeff(poly, factor, j) for j in range(len(poly) + 1)]
    return poly


def _gf_poly_coeff(a: list[int], b: list[int], index: int) -> int:
    value = 0
    for i, av in enumerate(a):
        j = index - i
        if 0 <= j < len(b):
            value ^= _gf_mul(av, b[j])
    return value


def _reed_solomon_ecc(data: list[int], degree: int) -> list[int]:
    generator = _rs_generator(degree)
    result = data[:] + [0] * degree
    for i, value in enumerate(data):
        if value == 0:
            continue
        factor = result[i]
        for j in range(len(generator)):
            result[i + j] ^= _gf_mul(generator[j], factor)
    return result[-degree:]


def _base_matrix(version: int) -> QRMatrix:
    size = 21 + (version - 1) * 4
    modules: list[list[bool | None]] = [[None for _ in range(size)] for _ in range(size)]
    reserved = [[False for _ in range(size)] for _ in range(size)]
    matrix = QRMatrix(modules, reserved)
    _finder(matrix, 0, 0)
    _finder(matrix, size - 7, 0)
    _finder(matrix, 0, size - 7)
    _timing(matrix)
    _reserve_format(matrix)
    _dark_module(matrix, version)
    if version >= 2:
        for x, y in _alignment_positions(version):
            if modules[y][x] is None:
                _alignment(matrix, x - 2, y - 2)
    return matrix


def _set(matrix: QRMatrix, x: int, y: int, value: bool, reserve: bool = True) -> None:
    if 0 <= x < matrix.size and 0 <= y < matrix.size:
        matrix.modules[y][x] = value
        if reserve:
            matrix.reserved[y][x] = True


def _finder(matrix: QRMatrix, left: int, top: int) -> None:
    for y in range(-1, 8):
        for x in range(-1, 8):
            xx, yy = left + x, top + y
            if not (0 <= xx < matrix.size and 0 <= yy < matrix.size):
                continue
            dark = 0 <= x <= 6 and 0 <= y <= 6 and (x in {0, 6} or y in {0, 6} or (2 <= x <= 4 and 2 <= y <= 4))
            _set(matrix, xx, yy, dark)


def _alignment(matrix: QRMatrix, left: int, top: int) -> None:
    for y in range(5):
        for x in range(5):
            dark = x in {0, 4} or y in {0, 4} or (x == 2 and y == 2)
            _set(matrix, left + x, top + y, dark)


def _alignment_positions(version: int) -> list[tuple[int, int]]:
    last = 21 + (version - 1) * 4 - 7
    if version == 2:
        coords = [6, 18]
    else:
        step = ((last - 6) + 1) // 2
        coords = [6, 6 + step, last]
    out = []
    for y in coords:
        for x in coords:
            if (x == 6 and y == 6) or (x == 6 and y == last) or (x == last and y == 6):
                continue
            out.append((x, y))
    return out


def _timing(matrix: QRMatrix) -> None:
    for i in range(8, matrix.size - 8):
        value = i % 2 == 0
        _set(matrix, i, 6, value)
        _set(matrix, 6, i, value)


def _reserve_format(matrix: QRMatrix) -> None:
    size = matrix.size
    for i in range(9):
        if i != 6:
            matrix.reserved[8][i] = True
            matrix.reserved[i][8] = True
    for i in range(8):
        matrix.reserved[8][size - 1 - i] = True
        matrix.reserved[size - 1 - i][8] = True


def _dark_module(matrix: QRMatrix, version: int) -> None:
    _set(matrix, 8, 4 * version + 9, True)


def _place_data(matrix: QRMatrix, bits: list[int]) -> None:
    bit_index = 0
    upward = True
    x = matrix.size - 1
    while x > 0:
        if x == 6:
            x -= 1
        y_range = range(matrix.size - 1, -1, -1) if upward else range(matrix.size)
        for y in y_range:
            for dx in (0, 1):
                xx = x - dx
                if matrix.reserved[y][xx]:
                    continue
                bit = bits[bit_index] if bit_index < len(bits) else 0
                matrix.modules[y][xx] = bool(bit)
                bit_index += 1
        upward = not upward
        x -= 2


def _copy_matrix(matrix: QRMatrix) -> QRMatrix:
    return QRMatrix([row[:] for row in matrix.modules], [row[:] for row in matrix.reserved])


def _mask(mask: int, x: int, y: int) -> bool:
    if mask == 0:
        return (x + y) % 2 == 0
    if mask == 1:
        return y % 2 == 0
    if mask == 2:
        return x % 3 == 0
    if mask == 3:
        return (x + y) % 3 == 0
    if mask == 4:
        return (x // 3 + y // 2) % 2 == 0
    if mask == 5:
        return ((x * y) % 2 + (x * y) % 3) == 0
    if mask == 6:
        return (((x * y) % 2 + (x * y) % 3) % 2) == 0
    return (((x + y) % 2 + (x * y) % 3) % 2) == 0


def _apply_mask(matrix: QRMatrix, mask: int) -> None:
    for y in range(matrix.size):
        for x in range(matrix.size):
            if not matrix.reserved[y][x] and _mask(mask, x, y):
                matrix.modules[y][x] = not bool(matrix.modules[y][x])


def _add_format_bits(matrix: QRMatrix, mask: int) -> None:
    bits = _int_bits(FORMAT_BITS_L[mask], 15)
    coords1 = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    coords2 = [(matrix.size - 1 - i, 8) for i in range(8)] + [(8, matrix.size - 7 + i) for i in range(7)]
    for bit, (x, y) in zip(bits, coords1):
        _set(matrix, x, y, bool(bit))
    for bit, (x, y) in zip(bits, coords2):
        _set(matrix, x, y, bool(bit))


def _penalty(modules: list[list[bool | None]]) -> int:
    size = len(modules)
    score = 0
    for rows in (modules, list(map(list, zip(*modules)))):
        for row in rows:
            run_color = row[0]
            run_len = 1
            for value in row[1:]:
                if value == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + run_len - 5
                    run_color = value
                    run_len = 1
            if run_len >= 5:
                score += 3 + run_len - 5
    for y in range(size - 1):
        for x in range(size - 1):
            value = modules[y][x]
            if modules[y][x + 1] == value and modules[y + 1][x] == value and modules[y + 1][x + 1] == value:
                score += 3
    dark = sum(1 for row in modules for value in row if value)
    percent = dark * 100 // (size * size)
    score += abs(percent - 50) // 5 * 10
    return score

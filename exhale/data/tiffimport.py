"""Conservative filename suggestions for TIFF channel imports."""

import re
from dataclasses import dataclass
from pathlib import Path

_ELEMENTS = frozenset(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn "
    "Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag "
    "Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm "
    "Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U "
    "Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl "
    "Mc Lv Ts Og".split()
)
_SHELL = re.compile(r"^[KLM](?:a|b|alpha|beta|\d+)?$", re.IGNORECASE)
_COMBINED = re.compile(r"^([A-Za-z]{1,2})([KLM](?:a|b|alpha|beta|\d+)?)$", re.IGNORECASE)


@dataclass(frozen=True)
class TiffImportProposal:
    """Editable sample and channel names inferred from one TIFF filename."""

    sample_name: str
    channel_key: str
    channel_name: str


def _element_symbol(text):
    symbol = text[:1].upper() + text[1:].lower()
    return symbol if symbol in _ELEMENTS else None


def infer_tiff_import(filename) -> TiffImportProposal:
    """Suggest editable sample and channel names from a TIFF filename."""
    stem = Path(filename).stem
    tokens = [token for token in re.split(r"[\s_.-]+", stem) if token]
    candidates = []
    for index, token in enumerate(tokens):
        combined = _COMBINED.fullmatch(token)
        if combined and (symbol := _element_symbol(combined.group(1))):
            candidates.append((True, index, symbol, combined.group(2), {index}))
        if symbol := _element_symbol(token):
            shell = None
            used = {index}
            if index + 1 < len(tokens) and _SHELL.fullmatch(tokens[index + 1]):
                shell = tokens[index + 1]
                used.add(index + 1)
            candidates.append((shell is not None, index, symbol, shell, used))

    if not candidates:
        return TiffImportProposal(stem, stem, stem)

    _has_shell, _index, element, shell, used = max(
        candidates, key=lambda candidate: (candidate[0], candidate[1])
    )

    if shell is None:
        key = element
    else:
        shell = shell[:1].upper() + shell[1:]
        key = f"{element}_{shell}"
    sample_tokens = [token for index, token in enumerate(tokens) if index not in used]
    sample_name = "_".join(sample_tokens) or stem
    return TiffImportProposal(sample_name, key, key)

#!/usr/bin/env python3
"""Generate the combined RGB guide used for XRF icon image generation."""

from argparse import ArgumentParser
import csv
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.interpolate import splprep, splev
from scipy.ndimage import gaussian_filter, label


HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
DEFAULT_OUTPUT = ICONS / "xrf_cells_x_guide.png"


def component_boundary(component: np.ndarray) -> np.ndarray:
    """Trace the exact outer grid boundary of a 4-connected component."""
    edges = []
    rows, columns = component.shape
    for row, column in zip(*np.nonzero(component)):
        if row == 0 or not component[row - 1, column]:
            edges.append(((column, row), (column + 1, row)))
        if column == columns - 1 or not component[row, column + 1]:
            edges.append(((column + 1, row), (column + 1, row + 1)))
        if row == rows - 1 or not component[row + 1, column]:
            edges.append(((column + 1, row + 1), (column, row + 1)))
        if column == 0 or not component[row, column - 1]:
            edges.append(((column, row + 1), (column, row)))

    following = {start: end for start, end in edges}
    start = edges[0][0]
    boundary = [start]
    point = following[start]
    while point != start:
        boundary.append(point)
        point = following[point]
    return np.asarray(boundary, dtype=np.float64)


def resample_boundary(boundary: np.ndarray, count: int) -> np.ndarray:
    """Place control points at equal distances along a closed polygon."""
    closed = np.vstack((boundary, boundary[0]))
    lengths = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    positions = np.linspace(0.0, cumulative[-1], count, endpoint=False)
    controls = []
    for position in positions:
        edge = min(np.searchsorted(cumulative, position, side="right") - 1,
                   len(boundary) - 1)
        fraction = (position - cumulative[edge]) / lengths[edge]
        controls.append(closed[edge] + fraction * (closed[edge + 1] - closed[edge]))
    return np.asarray(controls)


def spline_curve(controls: np.ndarray, samples: int = 192) -> np.ndarray:
    """Evaluate a closed cubic spline through the supplied control points."""
    spline, _ = splprep(
        (controls[:, 0], controls[:, 1]),
        per=True,
        k=min(3, len(controls) - 1),
        s=0.0,
    )
    parameter = np.linspace(0.0, 1.0, samples, endpoint=False)
    return np.column_stack(splev(parameter, spline))


def contour_length(curve: np.ndarray) -> float:
    return float(np.linalg.norm(np.roll(curve, -1, axis=0) - curve, axis=1).sum())


def curvature_cost(curve: np.ndarray) -> float:
    before = curve - np.roll(curve, 1, axis=0)
    after = np.roll(curve, -1, axis=0) - curve
    before /= np.maximum(np.linalg.norm(before, axis=1, keepdims=True), 1e-9)
    after /= np.maximum(np.linalg.norm(after, axis=1, keepdims=True), 1e-9)
    return float(np.mean(np.sum((after - before) ** 2, axis=1)))


def polygon_self_intersects(points: np.ndarray) -> bool:
    """Return whether non-adjacent edges of a closed polygon cross."""
    starts = points
    ends = np.roll(points, -1, axis=0)

    def cross(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]

    first = starts[:, None, :]
    first_end = ends[:, None, :]
    second = starts[None, :, :]
    second_end = ends[None, :, :]
    side_a = cross(first_end - first, second - first)
    side_b = cross(first_end - first, second_end - first)
    side_c = cross(second_end - second, first - second)
    side_d = cross(second_end - second, first_end - second)
    crossing = (side_a * side_b < 0.0) & (side_c * side_d < 0.0)

    count = len(points)
    indices = np.arange(count)
    adjacent = (
        indices[:, None] == indices[None, :]
    ) | ((indices[:, None] - indices[None, :]) % count == 1) | (
        (indices[None, :] - indices[:, None]) % count == 1
    )
    return bool(np.any(crossing & ~adjacent))


def rasterize_contours(
    contours: list[np.ndarray],
    diagonal_bridges: list[tuple[tuple[float, float], tuple[float, float], float]],
    size: int,
    grid_size: int,
) -> np.ndarray:
    canvas = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(canvas)
    scale = size / grid_size
    for contour in contours:
        draw.polygon([tuple(point * scale) for point in contour], fill=255)
    for start, end, width in diagonal_bridges:
        midpoint = (
            (start[0] + end[0]) / 2.0 + (end[1] - start[1]) * 0.06,
            (start[1] + end[1]) / 2.0 - (end[0] - start[0]) * 0.06,
        )
        points = [start, midpoint, end]
        draw.line(
            [tuple(coordinate * scale for coordinate in point) for point in points],
            fill=255,
            width=max(1, round(width * scale)),
            joint="curve",
        )
    return np.asarray(canvas) >= 128


def overlap_ratios(candidate: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    target_area = max(int(target.sum()), 1)
    outside = float((candidate & ~target).sum()) / target_area
    missed = float((target & ~candidate).sum()) / target_area
    return outside, missed


def contour_energy(
    controls: np.ndarray,
    target: np.ndarray,
    grid_size: int,
    maximum_spill: float,
    maximum_missed: float,
    length_coefficient: float,
    curvature_coefficient: float,
) -> tuple[float, np.ndarray, float, float, float]:
    if not np.isfinite(controls).all() or polygon_self_intersects(controls):
        return np.inf, np.empty((0, 2)), np.inf, np.inf, np.inf
    curve = spline_curve(controls)
    if not np.isfinite(curve).all() or polygon_self_intersects(curve[::4]):
        return np.inf, curve, np.inf, np.inf, np.inf
    candidate = rasterize_contours([curve], [], target.shape[0], grid_size)
    outside, missed = overlap_ratios(candidate, target)
    mask_area = target.sum() / (target.shape[0] / grid_size) ** 2
    length = contour_length(curve) / np.sqrt(max(mask_area, 1.0))
    spill_target_penalty = (outside - maximum_spill) ** 2
    spill_excess_penalty = max(0.0, outside - maximum_spill) ** 2
    missed_penalty = max(0.0, missed - maximum_missed) ** 2
    energy = (
        length_coefficient * length
        + curvature_coefficient * curvature_cost(curve)
        + 2500.0 * spill_target_penalty
        + 50000.0 * spill_excess_penalty
        + 80000.0 * missed_penalty
    )
    return energy, curve, outside, missed, length


def anneal_component(
    component: np.ndarray,
    connections: list[tuple[tuple[int, int], tuple[int, int]]],
    rng: np.random.Generator,
    steps: int,
    maximum_spill: float,
    maximum_missed: float,
    length_coefficient: float,
    curvature_coefficient: float,
    working_size: int = 128,
) -> tuple[np.ndarray, float, float, list[dict[str, float]]]:
    """Optimize one contour as a softly pulled, irregular rubber band."""
    grid_size = component.shape[0]
    scale = working_size / grid_size
    target_image = Image.fromarray(component.astype(np.uint8) * 255).resize(
        (working_size, working_size), Image.Resampling.NEAREST
    )
    target = np.asarray(target_image) >= 128

    topology_image = target_image.copy()
    topology_draw = ImageDraw.Draw(topology_image)
    for first, second in connections:
        topology_draw.line(
            (
                (first[1] + 0.5) * scale,
                (first[0] + 0.5) * scale,
                (second[1] + 0.5) * scale,
                (second[0] + 0.5) * scale,
            ),
            fill=255,
            width=max(2, round(scale * 0.12)),
        )
    topology = np.asarray(topology_image) >= 128
    boundary = component_boundary(topology) / scale
    perimeter = (
        4 * int(component.sum())
        - 2 * int((component[:, 1:] & component[:, :-1]).sum())
        - 2 * int((component[1:, :] & component[:-1, :]).sum())
    )
    control_count = int(np.clip(round(perimeter * 1.6), 8, 28))
    controls = resample_boundary(boundary, control_count)

    center = controls.mean(axis=0)
    direction = controls - center
    direction /= np.maximum(np.linalg.norm(direction, axis=1, keepdims=True), 1e-9)
    controls += direction * 0.08

    current = contour_energy(
        controls,
        target,
        grid_size,
        maximum_spill,
        maximum_missed,
        length_coefficient,
        curvature_coefficient,
    )
    best_controls = controls.copy()
    best = current
    diagnostics = []
    interval = max(1, steps // 60)
    proposed_count = 0
    accepted_count = 0
    uphill_count = 0
    uphill_accepted = 0
    uphill_sum = 0.0
    invalid_count = 0

    for step in range(steps):
        progress = step / max(steps - 1, 1)
        temperature = 1.0 * (0.02 / 1.0) ** progress
        proposal = controls.copy()
        block_size = int(rng.integers(3, min(6, control_count + 1)))
        first = int(rng.integers(control_count))
        indices = (first + np.arange(block_size)) % control_count

        tangent = (
            np.roll(controls, -1, axis=0) - np.roll(controls, 1, axis=0)
        )
        tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-9)
        normal = np.column_stack((tangent[:, 1], -tangent[:, 0]))
        window = np.sin(np.linspace(0.2, np.pi - 0.2, block_size))
        normal_move = rng.normal(0.0, 0.17) * window
        normal_move += rng.normal(0.0, 0.035, block_size)
        tangent_move = rng.normal(0.0, 0.035, block_size)
        proposal[indices] += (
            normal[indices] * normal_move[:, None]
            + tangent[indices] * tangent_move[:, None]
        )
        proposal = np.clip(proposal, -0.35, component.shape[0] + 0.35)

        proposed = contour_energy(
            proposal,
            target,
            grid_size,
            maximum_spill,
            maximum_missed,
            length_coefficient,
            curvature_coefficient,
        )
        proposed_count += 1
        if not np.isfinite(proposed[0]):
            invalid_count += 1
        difference = proposed[0] - current[0]
        if np.isfinite(difference) and difference > 0.0:
            uphill_count += 1
            uphill_sum += difference
        accepted = difference <= 0.0 or (
            np.isfinite(difference)
            and rng.random() < np.exp(-difference / temperature)
        )
        if accepted:
            accepted_count += 1
            if difference > 0.0:
                uphill_accepted += 1
            controls = proposal
            current = proposed
        if proposed[0] < best[0]:
            best_controls = proposal.copy()
            best = proposed

        if (step + 1) % interval == 0 or step + 1 == steps:
            diagnostics.append({
                "step": step + 1,
                "temperature": temperature,
                "current_energy": current[0],
                "best_energy": best[0],
                "current_length": current[4],
                "best_length": best[4],
                "current_spill": current[2],
                "best_spill": best[2],
                "current_missed": current[3],
                "best_missed": best[3],
                "acceptance_rate": accepted_count / proposed_count,
                "uphill_acceptance_rate": (
                    uphill_accepted / uphill_count if uphill_count else 0.0
                ),
                "mean_uphill_delta": uphill_sum / uphill_count if uphill_count else 0.0,
                "invalid_rate": invalid_count / proposed_count,
            })
            proposed_count = 0
            accepted_count = 0
            uphill_count = 0
            uphill_accepted = 0
            uphill_sum = 0.0
            invalid_count = 0

    return best_controls, best[2], best[3], diagnostics


def spline_mask(
    source: Path,
    size: int,
    seed: int,
    annealing_steps: int,
    maximum_spill: float,
    maximum_missed: float,
    length_coefficient: float,
    curvature_coefficient: float,
) -> tuple[np.ndarray, float, float, int, int, list[dict[str, float]]]:
    """Optimize smooth closed contours around the connected mask components."""
    small = np.asarray(Image.open(source).convert("L")) >= 128
    if small.shape[0] != small.shape[1] or size % small.shape[0]:
        raise ValueError("the source must be square and divide the output size")
    grid_size = small.shape[0]
    components, component_count = label(
        small, structure=np.array(((0, 1, 0), (1, 1, 1), (0, 1, 0)))
    )
    rng = np.random.default_rng(seed)
    diagonal_contacts = []
    for row, column in zip(*np.nonzero(small)):
        for dr, dc in ((1, -1), (1, 1)):
            other = (row + dr, column + dc)
            if not (0 <= other[0] < grid_size and 0 <= other[1] < grid_size):
                continue
            if small[other] and components[row, column] != components[other]:
                diagonal_contacts.append(((row, column), other))

    rng.shuffle(diagonal_contacts)
    merge_target = round(len(diagonal_contacts) / 2)
    selected_contacts = diagonal_contacts[:merge_target]

    parent = list(range(component_count + 1))

    def find(number: int) -> int:
        while parent[number] != number:
            parent[number] = parent[parent[number]]
            number = parent[number]
        return number

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[second_root] = first_root

    for first, second in selected_contacts:
        union(int(components[first]), int(components[second]))

    groups: dict[int, list[int]] = {}
    for number in range(1, component_count + 1):
        groups.setdefault(find(number), []).append(number)
    connections: dict[int, list[tuple[tuple[int, int], tuple[int, int]]]] = {
        root: [] for root in groups
    }
    for first, second in selected_contacts:
        connections[find(int(components[first]))].append((first, second))

    contours = []
    worst_spill = 0.0
    worst_missed = 0.0
    diagnostics = []
    for group_index, (root, numbers) in enumerate(groups.items(), start=1):
        component = np.isin(components, numbers)
        controls, spill, missed, component_diagnostics = anneal_component(
            component,
            connections[root],
            rng,
            annealing_steps,
            maximum_spill,
            maximum_missed,
            length_coefficient,
            curvature_coefficient,
        )
        for row in component_diagnostics:
            row["group"] = group_index
            row["source_components"] = len(numbers)
            row["diagonal_connections"] = len(connections[root])
        diagnostics.extend(component_diagnostics)
        contours.append(spline_curve(controls))
        worst_spill = max(worst_spill, spill)
        worst_missed = max(worst_missed, missed)

    result = rasterize_contours(contours, [], size, grid_size)

    return (
        result,
        worst_spill,
        worst_missed,
        merge_target,
        len(diagonal_contacts),
        diagnostics,
    )


def generate_guide(
    yellow_source: Path,
    blue_source: Path,
    output: Path,
    size: int = 512,
    blur: float = 8.0,
    maximum_spill: float = 0.20,
    maximum_missed: float = 0.05,
    annealing_steps: int = 1200,
    seed: int = 1618,
    length_coefficient: float = 1.0,
    curvature_coefficient: float = 0.08,
    annealing_log: Path | None = None,
) -> tuple[tuple[float, float, int, int], tuple[float, float, int, int]]:
    (
        yellow,
        yellow_spill,
        yellow_missed,
        yellow_merged,
        yellow_contacts,
        yellow_diagnostics,
    ) = spline_mask(
        yellow_source,
        size,
        seed,
        annealing_steps,
        maximum_spill,
        maximum_missed,
        length_coefficient,
        curvature_coefficient,
    )
    (
        blue,
        blue_spill,
        blue_missed,
        blue_merged,
        blue_contacts,
        blue_diagnostics,
    ) = spline_mask(
        blue_source,
        size,
        seed + 1100,
        annealing_steps,
        maximum_spill,
        maximum_missed,
        length_coefficient,
        curvature_coefficient,
    )

    background_rng = np.random.default_rng(9042)
    background_noise = gaussian_filter(
        background_rng.standard_normal((size, size)), blur * 2.25
    )
    background_noise /= max(float(background_noise.std()), 1e-9)

    guide = np.empty((size, size, 3), dtype=np.uint8)
    guide[:] = (7, 48, 24)
    guide = np.clip(
        guide.astype(np.float32)
        * (1.0 + background_noise[..., None] * 0.08),
        0,
        255,
    ).astype(np.uint8)

    yellow_color = np.array((218, 151, 18), dtype=np.float32)
    blue_color = np.array((16, 91, 198), dtype=np.float32)
    guide[yellow] = yellow_color
    guide[blue] = blue_color

    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(guide, "RGB").save(output)
    if annealing_log is not None:
        rows = []
        for color, color_rows in (
            ("yellow", yellow_diagnostics),
            ("blue", blue_diagnostics),
        ):
            for row in color_rows:
                rows.append({"color": color, **row})
        annealing_log.parent.mkdir(parents=True, exist_ok=True)
        with annealing_log.open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    return (
        yellow_spill, yellow_missed, yellow_merged, yellow_contacts
    ), (
        blue_spill, blue_missed, blue_merged, blue_contacts
    )


def parse_args() -> ArgumentParser:
    parser = ArgumentParser(
        description="Generate a combined RGB XRF guide from the 16px masks."
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"output PNG (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--blur", type=float, default=8.0)
    parser.add_argument("--maximum-spill", type=float, default=0.20)
    parser.add_argument("--maximum-missed", type=float, default=0.05)
    parser.add_argument("--annealing-steps", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=1618)
    parser.add_argument("--length-coefficient", type=float, default=1.0)
    parser.add_argument("--curvature-coefficient", type=float, default=0.08)
    parser.add_argument(
        "--annealing-log", type=Path,
        help="write interval-level simulated annealing diagnostics as CSV",
    )
    return parser


def main() -> None:
    args = parse_args().parse_args()
    yellow_metrics, blue_metrics = generate_guide(
        ICONS / "16-yellow-mask.png",
        ICONS / "16-blue-mask.png",
        args.output,
        args.size,
        args.blur,
        args.maximum_spill,
        args.maximum_missed,
        args.annealing_steps,
        args.seed,
        args.length_coefficient,
        args.curvature_coefficient,
        args.annealing_log,
    )
    print(args.output)
    print(
        f"yellow: worst component spill {yellow_metrics[0]:.3f}, "
        f"worst missed area {yellow_metrics[1]:.3f}, "
        f"merged diagonals {yellow_metrics[2]}/{yellow_metrics[3]}"
    )
    print(
        f"blue: worst component spill {blue_metrics[0]:.3f}, "
        f"worst missed area {blue_metrics[1]:.3f}, "
        f"merged diagonals {blue_metrics[2]}/{blue_metrics[3]}"
    )


if __name__ == "__main__":
    main()

"""首板研究结果 Markdown 渲染。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .stats import BucketStat


@dataclass
class GapStudyResult:
    generated_at: str
    base: dict
    factor_buckets: dict[str, list[BucketStat]] = field(default_factory=dict)
    ranking: list[dict] = field(default_factory=list)
    top: dict = field(default_factory=dict)
    excluded: dict = field(default_factory=dict)


def render_report(result: GapStudyResult) -> str:
    base = result.base
    lines = [
        "# 首板次日高开研究",
        f"_{result.generated_at}_",
        "",
        f"总样本：**{base['n']}** 个首板，胜率 **{base['win_rate']:.1%}**，"
        f"平均高开 **{base['mean_gap']:.2f}%**，中位高开 **{base['median_gap']:.2f}%**",
        "",
        f"排除口径：一字板 {result.excluded.get('yiziban', 0)}、"
        f"无 T+1 数据 {result.excluded.get('no_next_open', 0)}、"
        f"全部首板 {result.excluded.get('first_board', 0)}",
        "",
    ]
    if base["n"] == 0:
        lines.append("_样本不足，无法输出统计结论。_")
        return "\n".join(lines)

    lines.append("## 单因子最佳桶")
    if result.ranking:
        lines.append("| 因子 | 最佳桶 | 样本 | 胜率 | 平均高开 | 相对基线 |")
        lines.append("|---|---|---:|---:|---:|---:|")
        for r in result.ranking:
            lines.append(
                f"| {r['column']} | {r['best_bucket']} | {r['n']} | "
                f"{r['win_rate']:.1%} | {r['mean_gap']:.2f}% | "
                f"{r['lift']:+.1%} |"
            )
    else:
        lines.append("_无满足最小样本的因子。_")

    top = result.top
    lines.extend([
        "",
        "## 多因子 Top 20%",
        f"- Top {top['n']} 只：胜率 **{top['win_rate']:.1%}**，"
        f"平均高开 **{top['mean_gap']:.2f}%**，相对基线提升 **{top['lift']:+.1%}**",
        "",
        "## 特征分桶明细",
        "",
    ])
    for column, buckets in result.factor_buckets.items():
        lines.append(f"### {column}")
        lines.append("| 桶 | 样本 | 胜率 | 平均高开 |")
        lines.append("|---|---:|---:|---:|")
        for b in buckets:
            lines.append(
                f"| {b.bucket} | {b.n} | {b.win_rate:.1%} | {b.mean_gap:.2f}% |"
            )
        lines.append("")
    lines.append("---")
    lines.append("_口径：T 日收盘买入，T+1 开盘卖出，高开 ≥1% 算胜；一字板已排除。_")
    return "\n".join(lines)

"""结果分析：指标对比、精确符号检验结论、失败分析与迭代建议。"""
from __future__ import annotations


def analyze_results(results: dict, alpha: float = 0.05) -> dict:
    """对 results.json 的 runs 逐数据集/指标给出显著性结论与整体判断。"""
    per_item: list[dict] = []
    for run in results.get("runs", []):
        for metric, comp in (run.get("comparison") or {}).items():
            diff = comp.get("mean_diff", 0.0)
            p = comp.get("sign_test_p", 1.0)
            if diff > 0 and p < alpha:
                verdict = "significant_improvement"
            elif diff > 0:
                verdict = "improvement_not_significant"
            elif diff < 0 and p < alpha:
                verdict = "significant_degradation"
            else:
                verdict = "degradation_not_significant"
            per_item.append({
                "dataset": run.get("dataset"), "metric": metric,
                "mean_baseline": round(comp.get("mean_baseline", 0.0), 4),
                "mean_proposed": round(comp.get("mean_proposed", 0.0), 4),
                "mean_diff": round(diff, 4), "sign_test_p": round(p, 4),
                "verdict": verdict,
            })

    wins = sum(1 for v in per_item if v["verdict"] == "significant_improvement")
    losses = sum(1 for v in per_item if v["verdict"] == "significant_degradation")
    overall = ("improvement" if wins > losses and wins > 0
               else "degradation" if losses > wins
               else "parity")

    suggestions: list[str] = []
    high_var = [v for v in per_item if v.get("std_proposed", 0) > 0.05]
    if high_var:
        suggestions.append(f"{len(high_var)} 项指标方差偏高（std>0.05），建议增加随机种子或折数")
    if wins == 0 and losses == 0:
        suggestions.append("无显著差异：建议增大样本/折数，或引入更强的提出方法配置")
    if not suggestions:
        suggestions.append("结果稳定；可接入真实数据集与更强 estimator 规格")

    return {
        "per_item": per_item,
        "overall": overall,
        "n_improvements": wins,
        "n_degradations": losses,
        "suggestions": suggestions,
    }

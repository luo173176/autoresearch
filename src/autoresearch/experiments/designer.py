"""实验设计：把假设的 testability 落成可执行实验设计（数据集/基线/指标/CV/统计检验/预算）。

离线代理设计（DECISIONS.md D-022）：本机无 GPU/LLM 服务，检索类方法无法直接执行。
设计器生成「表格分类代理实验」——以 sklearn 内置小数据集验证
「提出方法（集成/组合代理）相对基线」的完整实验流程与统计检验；
接入真实数据集与模型后仅需替换 config.json 中的 estimator 规格，流程不变。
"""
from __future__ import annotations

from ..config import Settings

_PROPOSED_BY_SOURCE = {
    "combination": "gradient_boosting",  # 组合假设 → 集成代理
    "gap": "random_forest",
    "contradiction": "random_forest",
}


def design_from_hypothesis(hyp: dict, settings: Settings) -> dict:
    t = hyp.get("testability") or {}
    method = t.get("method") or "proposed_method"
    source = (hyp.get("metadata") or {}).get("source", "gap")
    proposed = _PROPOSED_BY_SOURCE.get(source, "gradient_boosting")
    datasets = [s.strip() for s in settings.experiment_datasets.split(",") if s.strip()]
    seeds = [int(x) for x in settings.experiment_seeds.split(",") if x.strip().isdigit()] or [0]
    return {
        "hypothesis_id": hyp["id"],
        "hypothesis_statement": (hyp.get("statement") or "")[:300],
        "task": "classification",
        "datasets": [{"name": d, "source": "sklearn"} for d in datasets],
        "baselines": [{"name": "logistic_regression", "estimator": "logistic_regression"}],
        "proposed": {"name": f"proposed({method[:40]})", "estimator": proposed},
        "metrics": ["accuracy", "f1_macro"],
        "cv": {"type": "stratified_kfold", "folds": settings.experiment_folds, "seeds": seeds},
        "stat_test": {
            "name": "exact_sign_test",
            "description": "proposed 与 baseline 逐折配对差的精确符号检验（二项精确 p 值，无 scipy 依赖）",
            "alpha": 0.05,
        },
        "ablations": [
            {"name": "seed_sensitivity", "description": f"多随机种子 {seeds} 下的方差与稳定性分析"}
        ],
        "budget": {"cpu_minutes": round(settings.experiment_timeout / 60), "gpu_hours": 0},
        "note": (
            f"原始假设方向：{method}。离线代理设计：表格分类任务上 "
            f"proposed={proposed} vs baseline=logistic_regression，"
            f"验证「组合优于单方法」的实验流程与统计检验；"
            f"接入真实数据集/模型后仅需替换 estimator 规格。"
        ),
    }

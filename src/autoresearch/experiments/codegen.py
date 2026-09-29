"""实验代码生成：渲染自包含、可复现的实验包到独立工作区（约束 4）。

输出 data/experiments/{experiment_id}/：
  config.json        实验设计（含 experiment_id）
  main.py            入口：数据加载 × 变体 × 多种子交叉验证 + 配对符号检验
  requirements.txt   scikit-learn / numpy
  README.md          运行说明
"""
from __future__ import annotations

import json
from pathlib import Path

_MAIN_TEMPLATE = '''"""AutoResearch 自动生成实验入口。

运行: python main.py --config config.json --output results.json
"""
import argparse
import json
import math
import time
from pathlib import Path

from sklearn.datasets import load_breast_cancer, load_digits, load_iris, load_wine, fetch_openml
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import LinearSVC

ESTIMATORS = {
    "logistic_regression": lambda: make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000)),
    "gradient_boosting": lambda: GradientBoostingClassifier(random_state=0),
    "random_forest": lambda: RandomForestClassifier(n_estimators=100, random_state=0),
    "linear_svm": lambda: make_pipeline(StandardScaler(), LinearSVC(max_iter=5000)),
}

LOADERS = {
    "iris": lambda: load_iris(return_X_y=True),
    "wine": lambda: load_wine(return_X_y=True),
    "breast_cancer": lambda: load_breast_cancer(return_X_y=True),
    "digits": lambda: (load_digits().data, load_digits().target),
}


def load_dataset(spec):
    name = str(spec.get("name", "")).lower()
    if str(spec.get("source", "")).lower() == "openml":
        ds = fetch_openml(spec["name"], version=1, as_frame=False)
        return ds.data, ds.target
    if name in LOADERS:
        return LOADERS[name]()
    raise ValueError(f"未知数据集: {spec}")


def metric_fn(name):
    if name == "accuracy":
        return accuracy_score
    if name.startswith("f1"):
        average = name.split("_", 1)[1] if "_" in name else "binary"
        return lambda y, p: f1_score(y, p, average=average)
    raise ValueError(f"不支持的指标: {name}")


def evaluate(X, y, make_estimator, metrics, folds, seeds):
    out = {m: [] for m in metrics}
    fns = {m: metric_fn(m) for m in metrics}
    for seed in seeds:
        skf = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
        for tr, te in skf.split(X, y):
            est = make_estimator()
            est.fit(X[tr], y[tr])
            pred = est.predict(X[te])
            for m in metrics:
                out[m].append(float(fns[m](y[te], pred)))
    return out


def mean(xs):
    return sum(xs) / len(xs)


def std(xs):
    m = mean(xs)
    return (sum((x - m) ** 2 for x in xs) / max(len(xs) - 1, 1)) ** 0.5


def sign_test(diffs):
    """精确符号检验：p = 2 * P(Bin(n, 0.5) <= min(wins, losses))。"""
    wins = sum(d > 0 for d in diffs)
    losses = sum(d < 0 for d in diffs)
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--output", default="results.json")
    args = ap.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    seeds = config["cv"]["seeds"]
    folds = config["cv"]["folds"]
    variants = [("baseline", b) for b in config["baselines"]] + [("proposed", config["proposed"])]

    results = {"experiment_id": config["experiment_id"], "started_at": time.time(), "runs": []}
    for ds_spec in config["datasets"]:
        X, y = load_dataset(ds_spec)
        per_variant = {}
        for role, spec in variants:
            metrics = evaluate(X, y, ESTIMATORS[spec["estimator"]], config["metrics"], folds, seeds)
            per_variant[role] = {"name": spec["name"], "estimator": spec["estimator"],
                                 "metrics": metrics}
        base = per_variant["baseline"]["metrics"]
        prop = per_variant["proposed"]["metrics"]
        comparison = {}
        for m in config["metrics"]:
            diffs = [p - b for p, b in zip(prop[m], base[m])]
            comparison[m] = {
                "mean_baseline": mean(base[m]), "std_baseline": std(base[m]),
                "mean_proposed": mean(prop[m]), "std_proposed": std(prop[m]),
                "mean_diff": mean(diffs), "sign_test_p": sign_test(diffs),
            }
        results["runs"].append({"dataset": ds_spec["name"],
                                "variants": per_variant, "comparison": comparison})

    results["status"] = "completed"
    Path(args.output).write_text(json.dumps(results, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(json.dumps({"status": "completed", "datasets": len(results["runs"])}))


if __name__ == "__main__":
    main()
'''


def generate_experiment_code(workspace: Path, design: dict, experiment_id: int) -> list[str]:
    """渲染实验包，返回文件名列表。"""
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = dict(design)
    cfg["experiment_id"] = experiment_id
    (workspace / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    (workspace / "main.py").write_text(_MAIN_TEMPLATE, encoding="utf-8")
    (workspace / "requirements.txt").write_text("scikit-learn>=1.5\nnumpy\n", encoding="utf-8")
    (workspace / "README.md").write_text(
        f"# AutoResearch 实验 #{experiment_id}\n\n"
        f"假设：{design.get('hypothesis_statement', '')}\n\n"
        f"运行：`python main.py --config config.json --output results.json`\n\n"
        f"{design.get('note', '')}\n",
        encoding="utf-8")
    return sorted(p.name for p in workspace.iterdir() if p.is_file())

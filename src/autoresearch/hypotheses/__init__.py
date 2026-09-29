"""假设生成：从知识图谱的矛盾、缺口与方法组合中产出可验证假设。

用法：
    from autoresearch.hypotheses import generate_hypotheses
    summary = generate_hypotheses(db, settings, project_id=1, max_hypotheses=50)
"""
from .generator import generate_hypotheses
from .ranker import rank, jaccard, score_candidate

__all__ = ["generate_hypotheses", "rank", "jaccard", "score_candidate"]

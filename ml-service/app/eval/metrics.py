from typing import List, Dict, Any, Set


def compute_extraction_f1(predicted_entities: List[str], ground_truth_entities: List[str]) -> Dict[str, float]:
    """
    Computes Precision, Recall, and F1 score for entity sets (exact/normalized match).
    Standard evaluation metric for n2c2 2018 ADE and CADEC benchmarks.
    """
    pred_set = set(e.strip().lower() for e in predicted_entities if e and e.strip())
    gold_set = set(e.strip().lower() for e in ground_truth_entities if e and e.strip())

    if not pred_set and not gold_set:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "tp": 0, "fp": 0, "fn": 0}
    if not pred_set or not gold_set:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": len(pred_set), "fn": len(gold_set)}

    tp = len(pred_set & gold_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


def compute_classification_metrics(preds: List[str], targets: List[str]) -> Dict[str, Any]:
    """
    Computes Accuracy, per-class Precision/Recall/F1, and Macro-F1 for severity levels.
    """
    if len(preds) != len(targets) or not preds:
        return {"accuracy": 0.0, "macro_f1": 0.0, "classes": {}}

    classes = sorted(list(set(targets) | set(preds)))
    correct = sum(1 for p, t in zip(preds, targets) if p == t)
    accuracy = correct / len(preds)

    class_metrics = {}
    f1_scores = []

    for c in classes:
        tp = sum(1 for p, t in zip(preds, targets) if p == c and t == c)
        fp = sum(1 for p, t in zip(preds, targets) if p == c and t != c)
        fn = sum(1 for p, t in zip(preds, targets) if p != c and t == c)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0

        class_metrics[c] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": sum(1 for t in targets if t == c),
        }
        f1_scores.append(f1)

    macro_f1 = sum(f1_scores) / len(f1_scores) if f1_scores else 0.0

    return {
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "class_breakdown": class_metrics,
    }


def compute_retrieval_mrr_and_recall(
    retrieved_items: List[List[str]], relevant_items: List[Set[str]], k: int = 5
) -> Dict[str, float]:
    """
    Computes Recall@K and Mean Reciprocal Rank (MRR@K) for RAG evidence retrieval.
    """
    if not retrieved_items or not relevant_items:
        return {"recall_at_k": 0.0, "mrr_at_k": 0.0}

    n = len(retrieved_items)
    recall_sum = 0.0
    reciprocal_ranks = []

    for retrieved, relevant in zip(retrieved_items, relevant_items):
        if not relevant:
            continue

        top_k = retrieved[:k]
        hits = [item for item in top_k if item in relevant]
        recall = len(hits) / len(relevant) if relevant else 0.0
        recall_sum += recall

        # First hit rank for MRR
        first_hit_rank = None
        for rank, item in enumerate(top_k, 1):
            if item in relevant:
                first_hit_rank = rank
                break

        reciprocal_ranks.append(1.0 / first_hit_rank if first_hit_rank else 0.0)

    avg_recall = recall_sum / n if n > 0 else 0.0
    avg_mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0

    return {
        "recall_at_k": round(avg_recall, 4),
        "mrr_at_k": round(avg_mrr, 4),
    }


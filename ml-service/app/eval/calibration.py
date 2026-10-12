import math
from typing import List, Dict, Tuple


def compute_expected_calibration_error(
    confidences: List[float], accuracies: List[int], num_bins: int = 10
) -> Dict[str, float]:
    """
    Computes Expected Calibration Error (ECE) and Maximum Calibration Error (MCE)
    to verify that model confidence scores reflect true empirical likelihood.
    """
    if len(confidences) != len(accuracies) or not confidences:
        return {"ece": 0.0, "mce": 0.0}

    n = len(confidences)
    bin_size = 1.0 / num_bins
    ece = 0.0
    mce = 0.0

    bins_data = []

    for i in range(num_bins):
        bin_lower = i * bin_size
        bin_upper = (i + 1) * bin_size

        # Find items falling within this bin
        bin_indices = [
            idx for idx, c in enumerate(confidences)
            if (bin_lower <= c < bin_upper) or (i == num_bins - 1 and bin_lower <= c <= bin_upper)
        ]

        if not bin_indices:
            continue

        bin_conf = sum(confidences[idx] for idx in bin_indices) / len(bin_indices)
        bin_acc = sum(accuracies[idx] for idx in bin_indices) / len(bin_indices)
        gap = abs(bin_acc - bin_conf)

        ece += (len(bin_indices) / n) * gap
        mce = max(mce, gap)

        bins_data.append({
            "bin": f"[{bin_lower:.1f}, {bin_upper:.1f}]",
            "count": len(bin_indices),
            "avg_confidence": round(bin_conf, 3),
            "empirical_accuracy": round(bin_acc, 3),
            "gap": round(gap, 3),
        })

    return {
        "ece": round(ece, 4),
        "mce": round(mce, 4),
        "bins": bins_data,
    }


def calibrate_confidence_temperature(score: float, temperature: float = 1.25) -> float:
    """
    Applies temperature scaling to prevent overconfidence in raw model logits/probabilities.
    T > 1 softens overconfident probabilities.
    """
    clamped = max(0.01, min(0.99, score))
    # Convert probability to log-odds, scale by temperature, then apply sigmoid
    logit = math.log(clamped / (1.0 - clamped))
    scaled_logit = logit / max(0.1, temperature)
    calibrated = 1.0 / (1.0 + math.exp(-scaled_logit))
    return round(calibrated, 2)


def _clip01(value):
    return max(0.0, min(1.0, float(value)))


def cascade_fusion(mechanism_score, ai_score, mechanism_weight=0.4):
    if not 0.0 <= mechanism_weight <= 1.0:
        raise ValueError("mechanism_weight must be between 0 and 1")
    return _clip01(mechanism_weight * mechanism_score + (1.0 - mechanism_weight) * ai_score)


def residual_fusion(mechanism_score, residual_score):
    return _clip01(float(mechanism_score) + float(residual_score))


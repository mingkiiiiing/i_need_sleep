# 算法模型交付包 完整版 V0.2

## 1. 说明

本目录包含：

```text
63 个最终模型
训练窗口：2005-2021
预测时效：T+1/3/7/15/30/60/90
数据版本：TAIHU_GRID_SYNTHETIC_AUGMENTATION_V0.4
声明边界：synthetic_development_only
```

模型选择、融合权重和阈值来自冻结的修正全矩阵选择清单。

## 2. 文件结构

```text
算法模型交付包_完整版_V0.2/
├── README.md
├── requirements.txt
├── models/
│   ├── T1-bloom-1d-s20260907.joblib
│   ├── T1-bloom-3d-s20260907.joblib
│   ├── ...
│   └── T7-spatial-90d-s20260907.joblib
├── code/
│   ├── modeling_v1/
│   └── synthetic_augmentation/
├── api/
│   ├── server.py
│   └── client_example.py
├── sample_inputs/
└── test_bundles.py
```

## 3. 模型清单

9 个任务变体 × 7 个时效：

- T1-bloom：水华发生
- T2-area：水华面积
- T2-coverage：水华覆盖率
- T3-density：蓝藻密度
- T4-biomass：蓝藻生物量
- T5-chla：叶绿素 a
- T6-risk_level：风险等级
- T6-probability：风险概率
- T7-spatial：空间范围

每个模型文件命名：

```text
<task>-<variant>-<horizon>d-s20260907.joblib
```

## 4. 安装依赖

```bash
pip install -r requirements.txt
```

## 5. 一键验证

Windows：

```powershell
$env:PYTHONPATH = "$PWD\code;$PWD"
python test_bundles.py
```

预期：

```text
ALL_63_MODELS_OK
```

## 6. HTTP 服务

启动：

```powershell
python api\server.py
```

服务地址：

```text
http://127.0.0.1:8002
```

健康检查：

```text
GET /health
```

预测：

```text
POST /predict
```

请求示例见 `sample_inputs/T1-bloom-3d.json`。

## 7. Python 调用

```python
import json
from pathlib import Path
import pandas as pd

from modeling_v1.predict import load_bundle, predict_batch

bundle = load_bundle(
    Path("models/T1-bloom-3d-s20260907.joblib")
)
sample = json.loads(
    Path("sample_inputs/T1-bloom-3d.json").read_text(encoding="utf-8")
)
result = predict_batch(bundle, pd.DataFrame([sample["features"]]))
print(result)
```

## 8. 声明

所有输出均为合成数据开发模型，不代表真实太湖预测精度。接口/前端必须保留 `synthetic_development_only` 标识。

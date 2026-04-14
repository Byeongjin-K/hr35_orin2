import json
import numpy as np
from pathlib import Path
from datetime import datetime
from dataclasses import asdict


def save_session(filepath: str, report, data_info: dict, params: dict):
    session = {
        'timestamp': datetime.now().isoformat(),
        'version': '1.0',
        'params': params,
        'data_info': data_info,
        'report': _report_to_dict(report) if report else None,
    }
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(session, f, indent=2, ensure_ascii=False, default=_json_default)


def load_session(filepath: str) -> dict:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_comparison_csv(filepath: str, experiments: dict):
    if not experiments:
        return
    exp_names = list(experiments.keys())
    metric_names = list(next(iter(experiments.values())).keys())
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write("Metric," + ",".join(exp_names) + "\n")
        for metric in metric_names:
            values = [f"{experiments[name].get(metric, 0):.6f}" for name in exp_names]
            f.write(f"{metric}," + ",".join(values) + "\n")


def _report_to_dict(report):
    d = {}
    for field_name in ['geometric', 'volume', 'excavation', 'surface']:
        obj = getattr(report, field_name, None)
        if obj:
            d[field_name] = asdict(obj)

    if report.cross_sections:
        cs_list = []
        for cs in report.cross_sections:
            cs_list.append({
                'position': cs['position'],
                'metrics': asdict(cs['metrics']),
            })
        d['cross_sections'] = cs_list

    return d


def _json_default(obj):
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Not serializable: {type(obj)}")

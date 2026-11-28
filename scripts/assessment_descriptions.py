"""수집 대상 System Evidence의 평가 기준 설명."""

from easm_agent.models import load_criteria

ITEM_DETAILS = {
    code: "\n".join((item["evidence"], f'{item["numerator"]} / {item["denominator"]}', item["limit"]))
    for code, item in load_criteria()["items"].items()
}

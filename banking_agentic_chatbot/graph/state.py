
from typing import Annotated, Optional, TypedDict

from langgraph.graph.message import add_messages


class GuardrailVerdict(TypedDict, total=False):
    allowed: bool
    category: str
    reason: str


class BankingState(TypedDict):
    messages: Annotated[list, add_messages]
    customer_id: str
    db_username: str
    language: Optional[str]
    input_guardrail: Optional[GuardrailVerdict]
    output_guardrail: Optional[GuardrailVerdict]

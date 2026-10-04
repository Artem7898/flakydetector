"""HTTP-specific input. Domain responses are shared with CLI, not duplicated."""

from pydantic import Field

from flakydetector.models.domain import AnalysisResponse as AnalysisResponse
from flakydetector.models.domain import ValueModel


class AnalysisRequest(ValueModel):
    file_content: str = Field(min_length=1, max_length=1_000_000)
    file_path: str = "test_sample.py"
    log_content: str = Field(default="", max_length=1_000_000)
    use_ml_classifier: bool = False

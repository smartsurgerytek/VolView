
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from dataclasses import field
import uuid
from attr import asdict
from pydantic import BaseModel
from pyparsing import Enum

class Shape(Enum):
    LINE = "Line"
    RECTANGLE = "Rectangle"
    
import re

def from_pascal(name: str) -> str:
    # Insert underscore before ANY capital letter
    # except the first one or when multiple capitals appear together (UID)
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

class Annotation(BaseModel):
        
    shape: Shape
    measurement_name: str
    measurement_value: Optional[float] = None
    sop_class_uid: str #= field(default_factory=lambda: str(uuid.uuid4()))
    series_instance_uid: str #= field(default_factory=lambda: str(uuid.uuid4()))
    sop_instance_uid: str #= field(default_factory=lambda: str(uuid.uuid4()))
    coordinates: List[float]

    # class Config:
    #     validate_by_name = True
    #     alias_generator = from_pascal

    # def __post_init__(self):
    #     self._validate_coordinates()

    @property
    def coord_count(self):
        return len(self.coordinates)

    @property
    def is_line(self):
        return self.shape == Shape.LINE

    @property
    def is_rectangle(self):
        return self.shape == Shape.RECTANGLE

    def validate_coordinates(self):
        if self.is_line and self.coord_count != 4:
            raise ValueError("LINE requires exactly 4 coordinate values (x1, y1, x2, y2).")
        if self.is_rectangle and self.coord_count != 10:
            raise ValueError("RECTANGLE requires exactly 10 coordinate values.")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["shape"] = self.shape.value
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Annotation":
        shape = data.get("shape")
        if isinstance(shape, str):
            shape = Shape(shape)
        return cls(
            shape=shape,
            measurement_name=data.get("measurement_name"),
            measurement_value=data.get("measurement_value"),
            series_instance_uid=data.get("series_instance_uid", str(uuid.uuid4())),
            sop_instance_uid=data.get("sop_instance_uid", str(uuid.uuid4())),
            coordinates=list(data.get("coordinates", [])),
            sop_class_uid=data.get("sop_class_uid", str(uuid.uuid4())),
        )

    def __repr__(self):
        coords_preview = (
            f"{len(self.coordinates)} values" if len(self.coordinates) > 6 else str(self.coordinates)
        )
        return (
            f"Annotation(shape={self.shape.value!r}, name={self.measurement_name!r}, "
            f"value={self.measurement_value!r}, series_uid={self.series_instance_uid!r}, "
            f"sop_uid={self.sop_instance_uid!r}, coords={coords_preview})"
        )

class Manifest(BaseModel):

    annotations: List[Annotation]
    study_instance_uid: str
    study_id: str
    patient_name: str
    patient_id: str
    patient_birth_date: str
    patient_sex: str
    raw_manifest: str
    
    # class Config:
    #     validate_by_name = True
    #     alias_generator = from_pascal
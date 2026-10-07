from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    lat: float
    lon: float
    region: str
    t_mean: float
    t_amp: float
    monsoon: float
    m_peak: int
    m_width: int
    rain_scale: float
    wind_scale: float
    coastal: bool = False

    @property
    def terrain(self) -> str:
        """IMD heat-wave station class: 'coastal', 'hilly' or 'plains'. PROPOSED from coordinates and the coastal
        flag: confirm against IMD's own station classification before relying on it."""
        if self.coastal:
            return "coastal"
        return "hilly" if self.id in HILLY_STATIONS else "plains"


HILLY_STATIONS = {"sxr"}      # Srinagar (about 1,600 m). Bengaluru and Pune sit on plateaus and are kept as plains


LOCATIONS: list[Location] = [
    Location("blr", "Bengaluru", 12.97, 77.59, "SOUTH", 24.5, 2.8, 0.6, 215, 60, 3.5, 9),
    Location("maa", "Chennai", 13.08, 80.27, "EAST_COAST", 28.5, 3.0, 0.8, 305, 35, 4.5, 11, True),
    Location("hyd", "Hyderabad", 17.38, 78.48, "CENTRAL", 26.5, 3.5, 0.7, 210, 45, 3.5, 9),
    Location("cok", "Kochi", 9.93, 76.27, "WEST_COAST", 27.3, 1.5, 1.0, 170, 50, 6.0, 9, True),
    Location("bom", "Mumbai", 19.08, 72.88, "WEST_COAST", 27.3, 3.0, 1.0, 195, 40, 7.0, 11, True),
    Location("pnq", "Pune", 18.52, 73.86, "CENTRAL", 25.0, 3.8, 0.8, 200, 40, 4.0, 9),
    Location("amd", "Ahmedabad", 23.02, 72.57, "CENTRAL", 27.5, 6.0, 0.7, 205, 35, 3.5, 10),
    Location("jai", "Jaipur", 26.91, 75.79, "NORTH", 26.0, 7.0, 0.55, 205, 35, 3.0, 10),
    Location("del", "Delhi", 28.61, 77.21, "NORTH", 25.5, 8.5, 0.6, 205, 35, 3.0, 9),
    Location("lko", "Lucknow", 26.85, 80.95, "NORTH", 25.5, 8.0, 0.7, 205, 40, 3.2, 8),
    Location("pat", "Patna", 25.59, 85.14, "EAST_NE", 26.0, 7.5, 0.8, 205, 40, 3.5, 8),
    Location("ccu", "Kolkata", 22.57, 88.36, "EAST_NE", 27.0, 4.5, 0.9, 205, 45, 5.0, 9, True),
    Location("gau", "Guwahati", 26.14, 91.74, "EAST_NE", 24.5, 5.0, 1.0, 185, 60, 6.0, 7),
    Location("bbi", "Bhubaneswar", 20.30, 85.82, "EAST_COAST", 27.5, 4.0, 0.9, 210, 40, 5.0, 10, True),
    Location("vtz", "Visakhapatnam", 17.69, 83.22, "EAST_COAST", 27.8, 3.5, 0.8, 240, 50, 4.0, 11, True),
    Location("nag", "Nagpur", 21.15, 79.09, "CENTRAL", 27.0, 6.0, 0.7, 205, 40, 3.5, 9),
    Location("bho", "Bhopal", 23.26, 77.41, "CENTRAL", 25.5, 6.0, 0.7, 205, 40, 3.5, 9),
    Location("ixc", "Chandigarh", 30.73, 76.78, "NORTH", 24.0, 8.5, 0.6, 205, 35, 3.5, 8),
    Location("sxr", "Srinagar", 34.08, 74.80, "NORTH", 13.0, 11.0, 0.25, 120, 60, 2.5, 7),
    Location("trv", "Thiruvananthapuram", 8.52, 76.94, "WEST_COAST", 27.5, 1.3, 0.9, 170, 55, 5.5, 8, True),
]
LOC_BY_ID = {l.id: l for l in LOCATIONS}
REGION_LIST = sorted({l.region for l in LOCATIONS})


def season_of_month(month: int) -> str:
    if month in (12, 1, 2):
        return "WINTER"
    if month in (3, 4, 5):
        return "PRE_MONSOON"
    if month in (6, 7, 8, 9):
        return "MONSOON"
    return "POST_MONSOON"

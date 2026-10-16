# TravelDB Phase 1: Data Quality & Graph Coverage Report

## 1. Executive Summary
- **Region**: Chennai – Vellore – Bengaluru Corridor (NH 48 / AH 45)
- **Total Road Nodes**: 45,518
- **Total Road Edges**: 59,468
- **Fuel Stations (Amenity=Fuel)**: 240
- **Emergency & Travel POIs**: 897

---

## 2. Graph Connectivity & Topological Integrity
- **Total Vertices in Network**: 45,518
- **Strongly Connected Components (SCC)**: 3901
- **Largest Strongly Connected Component (LSCC)**: 40,551 nodes (89.09% of network)
- **Topological Integrity Assessment**:
  - The dominant road network forms a cohesive giant component covering >90% of drivable corridors.
  - Minor isolated components represent disconnected service roads, dead-end parking structures, or unlinked dual-carriageway ramps.
  - Routing algorithms will restrict pathfinding to the LSCC to guarantee route reachability.

---

## 3. Road Classification & Speeds
### Road Types Breakdown
| Road Type | Segments Count | Total Length (km) |
| :--- | :--- | :--- |
| `primary` | 28,426 | 1,435.54 km |
| `secondary` | 20,872 | 908.42 km |
| `trunk` | 4,864 | 357.52 km |
| `primary_link` | 1,989 | 30.21 km |
| `trunk_link` | 1,421 | 50.17 km |
| `motorway` | 1,250 | 66.69 km |
| `motorway_link` | 427 | 9.84 km |
| `secondary_link` | 219 | 3.03 km |

### Speed Limit Coverage
| Speed Source | Segments Count | Percentage |
| :--- | :--- | :--- |
| `default` | 53,633 | 90.19% |
| `osm` | 5,835 | 9.81% |

> [!NOTE]
> Segments with `speed_source='default'` use official statutory speed limits mapped by road classification (e.g. 80 km/h for National Highway trunks, 65 km/h for State Highway primaries). No speed values are invented.

---

## 4. Fuel Stations & Spatial Snapping
- **Total Fuel Stations**: 240
- **Branded Stations**: 174 (72.5%)
- **Spatial Snapping Metrics**:
  - **Minimum Snap Distance**: 3.15 m
  - **Average Snap Distance**: 217.29 m
  - **Maximum Snap Distance**: 5232.64 m

### Top Fuel Brands
| Brand | Stations Count |
| :--- | :--- |
| Unknown / Independent | 66 |
| Bharat Petroleum | 56 |
| Indian Oil | 47 |
| Hindustan Petroleum | 41 |
| Shell | 12 |
| BP | 5 |
| Go Gas | 3 |
| Essar | 2 |

---

## 5. Travel & Emergency POIs
| POI Category | Count |
| :--- | :--- |
| `hospital` | 801 |
| `police` | 69 |
| `toll` | 23 |
| `charging_station` | 4 |

# Verdigris — Regions Reference

# This file is read by data/location.py to resolve ambiguous
# location inputs into standardized location objects.
# It is not injected into LLM prompts.
# Add entries as you expand coverage.

---

## U.S. States — Name to FIPS and Abbreviation

| State Name | Abbreviation | FIPS Code | Area (sq mi) | Region |
|---|---|---|---|---|
| Alabama | AL | 01 | 50645 | Southeast |
| Alaska | AK | 02 | 571951 | West |
| Arizona | AZ | 04 | 113594 | Southwest |
| Arkansas | AR | 05 | 52035 | Southeast |
| California | CA | 06 | 155779 | West |
| Colorado | CO | 08 | 103642 | Southwest |
| Connecticut | CT | 09 | 4842 | Northeast |
| Delaware | DE | 10 | 1949 | Northeast |
| Florida | FL | 12 | 53625 | Southeast |
| Georgia | GA | 13 | 57513 | Southeast |
| Hawaii | HI | 15 | 6423 | West |
| Idaho | ID | 16 | 82643 | West |
| Illinois | IL | 17 | 55519 | Midwest |
| Indiana | IN | 18 | 35826 | Midwest |
| Iowa | IA | 19 | 55857 | Midwest |
| Kansas | KS | 20 | 81759 | Midwest |
| Kentucky | KY | 21 | 39486 | Southeast |
| Louisiana | LA | 22 | 43204 | Southeast |
| Maine | ME | 23 | 30843 | Northeast |
| Maryland | MD | 24 | 9707 | Northeast |
| Massachusetts | MA | 25 | 7800 | Northeast |
| Michigan | MI | 26 | 56804 | Midwest |
| Minnesota | MN | 27 | 79627 | Midwest |
| Mississippi | MS | 28 | 46923 | Southeast |
| Missouri | MO | 29 | 68742 | Midwest |
| Montana | MT | 30 | 145546 | West |
| Nebraska | NE | 31 | 76824 | Midwest |
| Nevada | NV | 32 | 109781 | West |
| New Hampshire | NH | 33 | 8953 | Northeast |
| New Jersey | NJ | 34 | 7354 | Northeast |
| New Mexico | NM | 35 | 121298 | Southwest |
| New York | NY | 36 | 47126 | Northeast |
| North Carolina | NC | 37 | 48618 | Southeast |
| North Dakota | ND | 38 | 68976 | Midwest |
| Ohio | OH | 39 | 40861 | Midwest |
| Oklahoma | OK | 40 | 68595 | Southwest |
| Oregon | OR | 41 | 95988 | West |
| Pennsylvania | PA | 42 | 44743 | Northeast |
| Rhode Island | RI | 44 | 1034 | Northeast |
| South Carolina | SC | 45 | 30061 | Southeast |
| South Dakota | SD | 46 | 75811 | Midwest |
| Tennessee | TN | 47 | 41235 | Southeast |
| Texas | TX | 48 | 261232 | Southwest |
| Utah | UT | 49 | 82170 | West |
| Vermont | VT | 50 | 9217 | Northeast |
| Virginia | VA | 51 | 39490 | Southeast |
| Washington | WA | 53 | 66456 | West |
| West Virginia | WV | 54 | 24038 | Southeast |
| Wisconsin | WI | 55 | 54158 | Midwest |
| Wyoming | WY | 56 | 97093 | West |
| District of Columbia | DC | 11 | 61 | Northeast |

---

## U.S. Region Groupings

Used for regional benchmark comparisons and report context.

| Region | States |
|---|---|
| Northeast | CT, DE, DC, MA, MD, ME, NH, NJ, NY, PA, RI, VT |
| Southeast | AL, AR, FL, GA, KY, LA, MS, NC, SC, TN, VA, WV |
| Midwest | IA, IL, IN, KS, MI, MN, MO, ND, NE, OH, SD, WI |
| Southwest | AZ, CO, NM, OK, TX |
| West | AK, CA, HI, ID, MT, NV, OR, UT, WA, WY |

---

## U.S. Common Aliases

Alternate names and abbreviations location.py should resolve.

| Input | Resolves To |
|---|---|
| Cali | California |
| Cali. | California |
| SoCal | California |
| NorCal | California |
| NY | New York |
| NYC | New York |
| New York City | New York |
| TX | Texas |
| Tex | Texas |
| FL | Florida |
| Fla | Florida |
| DC | District of Columbia |
| Washington DC | District of Columbia |
| Washington D.C. | District of Columbia |
| PNW | Washington |
| US-CA | California |
| US-TX | Texas |
| US-FL | Florida |
| US-NY | New York |

---

## U.S. Utility Territories — Major ISOs and RTOs

Used to provide grid context in reports. Location.py maps states
to their primary ISO/RTO for interconnection context.

| ISO/RTO | States (primary) | Notes |
|---|---|---|
| ERCOT | TX | Operates independently — no interstate interconnection |
| CAISO | CA | California grid operator |
| PJM | PA, NJ, MD, DE, VA, WV, OH, IN, IL, MI, NC, KY, TN | Largest U.S. RTO |
| MISO | MN, IA, IL, IN, MI, WI, MO, ND, SD, MT, KY, AR, MS, LA | Central U.S. |
| SPP | KS, OK, NE, SD, ND, WY, CO, NM, TX (panhandle) | Southern Plains |
| NYISO | NY | New York state grid |
| ISO-NE | CT, MA, ME, NH, RI, VT | New England |
| SERC | AL, FL, GA, SC, NC (non-PJM) | Southeast — no single RTO |
| WECC | AZ, CO, ID, MT, NV, NM, OR, UT, WA, WY | Western interconnection |

---

## International Countries — Name to ISO Codes

| Country Name | ISO2 | ISO3 | Region | World Bank Region |
|---|---|---|---|---|
| Australia | AU | AUS | Oceania | East Asia & Pacific |
| Austria | AT | AUT | Europe | Europe & Central Asia |
| Belgium | BE | BEL | Europe | Europe & Central Asia |
| Brazil | BR | BRA | South America | Latin America & Caribbean |
| Canada | CA | CAN | North America | North America |
| Chile | CL | CHL | South America | Latin America & Caribbean |
| China | CN | CHN | Asia | East Asia & Pacific |
| Colombia | CO | COL | South America | Latin America & Caribbean |
| Denmark | DK | DNK | Europe | Europe & Central Asia |
| Egypt | EG | EGY | Africa | Middle East & North Africa |
| Ethiopia | ET | ETH | Africa | Sub-Saharan Africa |
| France | FR | FRA | Europe | Europe & Central Asia |
| Germany | DE | DEU | Europe | Europe & Central Asia |
| Ghana | GH | GHA | Africa | Sub-Saharan Africa |
| India | IN | IND | Asia | South Asia |
| Indonesia | ID | IDN | Asia | East Asia & Pacific |
| Italy | IT | ITA | Europe | Europe & Central Asia |
| Japan | JP | JPN | Asia | East Asia & Pacific |
| Kenya | KE | KEN | Africa | Sub-Saharan Africa |
| Mexico | MX | MEX | North America | Latin America & Caribbean |
| Morocco | MA | MAR | Africa | Middle East & North Africa |
| Netherlands | NL | NLD | Europe | Europe & Central Asia |
| Nigeria | NG | NGA | Africa | Sub-Saharan Africa |
| Norway | NO | NOR | Europe | Europe & Central Asia |
| Pakistan | PK | PAK | Asia | South Asia |
| Peru | PE | PER | South America | Latin America & Caribbean |
| Philippines | PH | PHL | Asia | East Asia & Pacific |
| Poland | PL | POL | Europe | Europe & Central Asia |
| Portugal | PT | PRT | Europe | Europe & Central Asia |
| Saudi Arabia | SA | SAU | Middle East | Middle East & North Africa |
| South Africa | ZA | ZAF | Africa | Sub-Saharan Africa |
| South Korea | KR | KOR | Asia | East Asia & Pacific |
| Spain | ES | ESP | Europe | Europe & Central Asia |
| Sweden | SE | SWE | Europe | Europe & Central Asia |
| Tanzania | TZ | TZA | Africa | Sub-Saharan Africa |
| Thailand | TH | THA | Asia | East Asia & Pacific |
| Turkey | TR | TUR | Europe/Asia | Europe & Central Asia |
| Uganda | UG | UGA | Africa | Sub-Saharan Africa |
| United Kingdom | GB | GBR | Europe | Europe & Central Asia |
| United States | US | USA | North America | North America |
| Uruguay | UY | URY | South America | Latin America & Caribbean |
| Vietnam | VN | VNM | Asia | East Asia & Pacific |

---

## International Common Aliases

| Input | Resolves To |
|---|---|
| Deutschland | Germany |
| Allemagne | Germany |
| UK | United Kingdom |
| Britain | United Kingdom |
| Great Britain | United Kingdom |
| England | United Kingdom |
| UAE | United Arab Emirates |
| Korea | South Korea |
| Republic of Korea | South Korea |
| Oz | Australia |
| Brasil | Brazil |
| Holland | Netherlands |
| Espana | Spain |
| España | Spain |
| Turkiye | Turkey |
| Türkiye | Turkey |
| Ivory Coast | Côte d'Ivoire |
| USA | United States |
| U.S. | United States |
| U.S.A. | United States |
| America | United States |

---

## PVGIS Uncertainty Regions

Used by report.md Rule I-3 to flag higher uncertainty in solar
output estimates. location.py sets a pvgis_uncertainty field
on the location object for these regions.

| Region | Countries | Uncertainty Level |
|---|---|---|
| Southeast Asia | TH, VN, PH, ID, MY, MM, KH, LA | High |
| South America (non-Chile) | BR, CO, PE, EC, BO, PY, UY, VE, GY, SR | Medium-High |
| Central America | MX (south), GT, BZ, HN, SV, NI, CR, PA | Medium |
| West Africa | NG, GH, CI, SN, ML, BF, NE, TD, CM | Medium |
| South Asia | PK, BD, LK, NP | Medium |
| Europe | All EU + UK + NO + CH | Low — best validated |
| North Africa | MA, DZ, TN, LY, EG | Low — well validated |
| East Africa | KE, TZ, UG, ET, RW | Medium |
| Southern Africa | ZA, ZW, ZM, MZ, BW, NA | Low-Medium |
| Australia | AU | Low — well validated |
| Chile | CL | Low — Atacama well studied |

---

## How location.py Uses This File

```python
# location.py loads this file at startup and builds lookup dicts:

# US_STATES: maps state name/abbr → {fips, abbr, name, area_sqmi, region, iso_rto}
# US_ALIASES: maps alternate names → canonical state name
# COUNTRIES: maps country name → {iso2, iso3, name, wb_region}
# INTL_ALIASES: maps alternate names → canonical country name
# PVGIS_UNCERTAINTY: maps iso2 → uncertainty level string

# Resolution priority for any input string:
# 1. Check US_ALIASES → resolve to canonical state name
# 2. Check US_STATES by name or abbreviation
# 3. Check INTL_ALIASES → resolve to canonical country name
# 4. Check COUNTRIES by name, ISO2, or ISO3
# 5. Check if input looks like a ZIP code (5 digits) → use pgeocode
# 6. Check if input is comma-separated → split and resolve each part
# 7. If unresolvable → return None with error message

# Output object:
# {
#   "name": str,              canonical resolved name
#   "lat": float,             centroid latitude
#   "lon": float,             centroid longitude
#   "is_us": bool,
#   "scope": str,             "state" | "zip" | "country" | "multi"
#   "country": str,           ISO2 code
#   "fips": str | None,       U.S. only
#   "state_abbr": str | None, U.S. only
#   "region": str | None,     U.S. region or World Bank region
#   "iso_rto": str | None,    U.S. only
#   "pvgis_uncertainty": str  "low" | "medium" | "high" — intl only
# }
```

---

## U.S. State Centroids

Used by nasa.py and pvwatts.py when a state-level (not ZIP)
location is provided. These are geographic centroids, not
population centroids.

| State | Lat | Lon |
|---|---|---|
| AL | 32.806671 | -86.791130 |
| AK | 61.370716 | -152.404419 |
| AZ | 33.729759 | -111.431221 |
| AR | 34.969704 | -92.373123 |
| CA | 36.116203 | -119.681564 |
| CO | 39.059811 | -105.311104 |
| CT | 41.597782 | -72.755371 |
| DE | 39.318523 | -75.507141 |
| FL | 27.766279 | -81.686783 |
| GA | 33.040619 | -83.643074 |
| HI | 21.094318 | -157.498337 |
| ID | 44.240459 | -114.478828 |
| IL | 40.349457 | -88.986137 |
| IN | 39.849426 | -86.258278 |
| IA | 42.011539 | -93.210526 |
| KS | 38.526600 | -96.726486 |
| KY | 37.668140 | -84.670067 |
| LA | 31.169960 | -91.867805 |
| ME | 44.693947 | -69.381927 |
| MD | 39.063946 | -76.802101 |
| MA | 42.230171 | -71.530106 |
| MI | 43.326618 | -84.536095 |
| MN | 45.694454 | -93.900192 |
| MS | 32.741646 | -89.678696 |
| MO | 38.456085 | -92.288368 |
| MT | 46.921925 | -110.454353 |
| NE | 41.125370 | -98.268082 |
| NV | 38.313515 | -117.055374 |
| NH | 43.452492 | -71.563896 |
| NJ | 40.298904 | -74.521011 |
| NM | 34.840515 | -106.248482 |
| NY | 42.165726 | -74.948051 |
| NC | 35.630066 | -79.806419 |
| ND | 47.528912 | -99.784012 |
| OH | 40.388783 | -82.764915 |
| OK | 35.565342 | -96.928917 |
| OR | 44.572021 | -122.070938 |
| PA | 40.590752 | -77.209755 |
| RI | 41.680893 | -71.511780 |
| SC | 33.856892 | -80.945007 |
| SD | 44.299782 | -99.438828 |
| TN | 35.747845 | -86.692345 |
| TX | 31.054487 | -97.563461 |
| UT | 40.150032 | -111.862434 |
| VT | 44.045876 | -72.710686 |
| VA | 37.769337 | -78.169968 |
| WA | 47.400902 | -121.490494 |
| WV | 38.491226 | -80.954453 |
| WI | 44.268543 | -89.616508 |
| WY | 42.755966 | -107.302490 |
| DC | 38.897438 | -77.026817 |
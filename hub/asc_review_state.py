#!/usr/bin/env python3
"""Print the beta review state of one FractRoam build: python asc_review_state.py 13"""
import pathlib, sys
sys.path.insert(0, "/Users/kaolin/dev/FractRoam/scripts")
from asc_screenshots import ASC
APP = "1043441882"
build = sys.argv[1]
a = ASC()
bs = a.get("/v1/builds", **{"filter[app]": APP, "filter[version]": build, "limit": 5})["data"]
if not bs:
    print("NO_BUILD"); sys.exit(2)
bid = bs[0]["id"]
try:
    sub = a.get(f"/v1/builds/{bid}/betaAppReviewSubmission")["data"]
    state = sub["attributes"]["betaReviewState"] if sub else "NO_SUBMISSION"
except Exception as e:
    state = f"ERR {e}"
det = a.get(f"/v1/builds/{bid}/buildBetaDetail")["data"]["attributes"]
print(f"build {build} id={bid} betaReviewState={state} external={det.get('externalBuildState')}")

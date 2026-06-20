#!/usr/bin/env python3
"""Update image repository and tag in a Hermes HelmRelease YAML file."""

import sys
import yaml

path = sys.argv[1]
image_repo, image_tag = sys.argv[2], sys.argv[3]

with open(path) as f:
    docs = list(yaml.safe_load_all(f))

docs[0]["spec"]["values"]["image"] = {"repository": image_repo, "tag": image_tag}

with open(path, "w") as f:
    yaml.dump(docs[0], f, default_flow_style=False, sort_keys=False)

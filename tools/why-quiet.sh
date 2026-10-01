#!/bin/sh
# [why-quiet] On the station host: why are the DJs quiet? The station answers.
#   sh tools/why-quiet.sh
docker exec spark-agent python3 -c "import os,urllib.request as u;r=u.Request('http://127.0.0.1:8096/api/dj/why-quiet?text=1',headers={'Authorization':'Bearer '+os.environ['SPARK_AGENT_API_KEY']});print(u.urlopen(r,timeout=30).read().decode())"

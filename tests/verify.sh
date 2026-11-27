#!/bin/sh
# Ground truth for realm-jheapo: every figure the realm reports, re-asked of jheapo's REST
# interface directly and required to agree exactly. Exits nonzero on any drift; the last line on
# success is exactly "ALL CHECKS PASS".
#
#   APPLIANCE=http://127.0.0.1:11043 AUTH=user:pass [JHEAPO=http://127.0.0.1:7071/rest/v1] sh tests/verify.sh
#
# Needs a jheapo serving one analysed dump (`bin/jheapo-rest.sh <dump.hprof>` in jheapo), licensed
# for the drill-downs, reachable both from here (JHEAPO) and from the appliance (apis/jheapo.yaml's
# server, host.docker.internal:7071 by default). No key: jheapo's REST interface takes none.
#
#   L0 jheapo itself      the reference figures, read from its tabs and drill-downs
#   L1 every view         each view answers BY NAME, on its defaults (required params taken from L0)
#   L2 reconciliation     the views' figures equal L0's, to the row
#   L3 cost               a pushed-down filter is one jheapo call; a repeat read is answered from cache
set -e
cd "$(dirname "$0")/.."
exec python3 tests/verify.py "$@"

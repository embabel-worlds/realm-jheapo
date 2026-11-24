"""realm-jheapo's battery: see tests/verify.sh for the ladder and the environment it reads."""
import base64, glob, json, os, re, sys, urllib.parse, urllib.request

APPLIANCE = os.environ.get("APPLIANCE", "http://127.0.0.1:11043").rstrip("/")
JHEAPO = os.environ.get("JHEAPO", "http://127.0.0.1:7071/rest/v1").rstrip("/")
AUTH = os.environ.get("AUTH") or sys.exit("set AUTH (user:pass)")
HEADERS = {"Authorization": "Basic " + base64.b64encode(AUTH.encode()).decode(), "Content-Type": "application/json"}
failures = []


def check(name, expected, actual):
    if expected == actual:
        print("  ok   %s = %s" % (name, str(expected)[:100]))
    else:
        print("  FAIL %s: expected %s, got %s" % (name, str(expected)[:200], str(actual)[:200]))
        failures.append(name)


def jheapo(path, **params):
    url = JHEAPO + path + ("?" + urllib.parse.urlencode(params) if params else "")
    return json.load(urllib.request.urlopen(url, timeout=120))


def invoke(name, args=None):
    req = urllib.request.Request("%s/api/v1/views/%s/invoke" % (APPLIANCE, name),
                                 data=json.dumps({"args": args or {}}).encode(), headers=HEADERS, method="POST")
    try:
        return json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        return {"error": "%s %s" % (e.code, e.read().decode(errors="replace")[:300])}


def rows(env):
    return env.get("data") or []


def calls(env):
    return (env.get("metrics") or {}).get("externalCalls")


print("== L0: ground truth, from jheapo directly ==")
status = jheapo("/status")
check("jheapo has finished analysing its dump", True, status.get("done"))
overview = jheapo("/tabs/overview")
threads = jheapo("/tabs/threads")["threads"]
retained = jheapo("/retained", n=500)
suspects = jheapo("/leak-suspects", n=50)
dominators = jheapo("/dominators", n=100)
waste = jheapo("/tabs/waste")["findings"]
loaders = jheapo("/tabs/classloaderDetail")["groups"]
final = jheapo("/tabs/finalization")
strings = jheapo("/tabs/strings")
collections = jheapo("/tabs/collections")
humongous = jheapo("/tabs/humongous")
top = retained[0]
instances = jheapo("/batch/instances", classIds=top["classId"], n=25)
oid = suspects[0]["oid"]
holders = jheapo("/batch/holders", oids=oid)
path = jheapo("/batch/paths", oids=oid)
print("  heapBytes=%s classes=%s threads=%d retainers=%d suspects=%d top=%s" % (
    overview.get("heapBytes"), overview.get("classes"), len(threads), len(retained), len(suspects), top["className"]))

print("== L1: every view answers by name, on its defaults ==")
required = {"classId": top["classId"], "oid": oid, "className": top["className"], "class": top["className"],
            "package": top["packageName"], "field": "java.util.HashMap.table", "subject": top["className"],
            "center": "org.springframework.util.LinkedMultiValueMap",
            # The jar realm-java-code ships, which this realm requires, so it is always there. It is
            # not the dump's application: a view joining heap rows to it matches none of them.
            "jar": "data/jars/spring-core-6.2.18.jar"}
# Views that read the application's code have nothing to match without a jar the world holds; the
# engine then answers FETCHED_NOT_MATCHED (heap rows fetched, none of them the application's), which
# is the honest answer here and is the only refusal accepted, and only from these views.
needs_jar = {"HeapFindingsStacksInYourCode", "HeapFindingsStaticPins", "HeapFindingsIdentityKeys",
             "HeapFindingsYourDominators", "HeapFieldGrowthCode", "HeapCenterLifecycle", "HeapAppFieldGrowth",
             "HeapAppFieldCode", "HeapAppClassSource", "HeapConcernCode", "JheapoRetainerWritersInFailures",
             "JheapoFailingCodeOnLiveStacks"}
V = {}
for f in sorted(glob.glob("views/*.yml")):
    for name, params in re.findall(r"^- name: (\w+)\n(?:  description:.*\n)?(?:  params:\n((?:    .*\n)+))?", open(f).read(), re.M):
        needed = {p: required[p] for p in re.findall(r"^    (\w+): \{[^}]*required: true", params, re.M)}
        env = invoke(name, needed)
        V[name] = env
        problem = env.get("error") or (env.get("errors") or None)
        if name in needs_jar and isinstance(problem, dict) and problem.get("reason") == "FETCHED_NOT_MATCHED":
            problem = None
        check("%s answers" % name, None, problem)
        if problem:
            print("       %s" % json.dumps({k: v for k, v in env.items() if k != "data"})[:1500])

def kg(cypher, params):
    req = urllib.request.Request("%s/api/v1/admin/kg/execute" % APPLIANCE, data=json.dumps({"cypher": cypher, "params": params}).encode(),
                                 headers=HEADERS, method="POST")
    try:
        return json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        return {"error": "%s %s" % (e.code, e.read().decode(errors="replace")[:300])}


if (V["HeapCenterLifecycle"].get("error")):
    # Which branch of the lifecycle a source failed in: each run on its own.
    P = {"jar": required["jar"], "center": required["center"], "carrier": ""}
    for label, q in [
        ("born", "MATCH (j:Jar {path: $jar})-[:HAS_CALL]->(b:JavaMethodCall {calleeOwner: $center, calleeName: '<init>'}) RETURN count(b) AS n"),
        ("construction", "MATCH (j:Jar {path: $jar})-[:HAS_METHOD]->(m:JavaMethod {owner: $center, name: '<init>'})-[:MAKES_CALL]->(k:JavaMethodCall {internal: true}) RETURN count(k) AS n"),
        ("calls", "MATCH (j:Jar {path: $jar})-[:HAS_CALL]->(e:JavaMethodCall) WHERE e.calleeName IN ['put','remove','clear'] RETURN count(e) AS n"),
        ("sites", "MATCH (j:Jar {path: $jar})-[:HAS_CALL]->(e:JavaMethodCall) WHERE e.calleeName IN ['put','remove','clear'] OPTIONAL MATCH (e)-[:AT_SITE]->(cs:JavaCallSite) RETURN count(e) AS n, count(cs) AS sites"),
        ("carrier", "MATCH (j:Jar {path: $jar})-[:HAS_FIELD]->(gf:JavaField {key: $carrier}) RETURN count(gf) AS n"),
    ]:
        r = kg(q, P)
        print("       diag %s: %s" % (label, json.dumps({k: r.get(k) for k in ("rows", "error", "warnings", "outcome") if k in r})[:600]))

print("== L2: the views reconcile with jheapo ==")
o = rows(V["HeapOverviewTotals"])
check("overview: one row", 1, len(o))
for k, col in (("heapBytes", "heapBytes"), ("classes", "classes"), ("instances", "instances"),
               ("gcRootCount", "gcRoots"), ("duplicateStringWaste", "duplicateStringWaste"),
               ("pendingFinalization", "pendingFinalization")):
    check("overview: %s" % k, overview.get(k), o[0].get(col) if o else None)
r = rows(V["HeapAppRetainers"])
check("retainers: rows", len(retained), len(r))
check("retainers: retained bytes by class", {x["classId"]: x["retainedBytes"] for x in retained},
      {x["classId"]: x["retainedBytes"] for x in r})
r = rows(V["HeapAppLeakSuspects"])
check("leak suspects: rows", len(suspects), len(r))
check("leak suspects: retained by oid", {x["oid"]: x["retainedSize"] for x in suspects}, {x["oid"]: x["retainedSize"] for x in r})
r = rows(V["HeapAppInstances"])
check("instances of %s: oids" % top["className"], sorted(x["oid"] for x in instances), sorted(x["oid"] for x in r))
r = rows(V["HeapAppHolders"])
check("holders of %s: holder oids" % oid, sorted(x["oid"] for x in holders), sorted(x["oid"] for x in r))
r = rows(V["HeapAppPath"])
check("path of %s: steps" % oid, [(x["step"], x["oid"]) for x in sorted(path, key=lambda x: x["step"])],
      [(x["step"], x["oid"]) for x in r])
r = rows(V["HeapFindingsThreads"])
check("threads: rows", len(threads), len(r))
check("threads: by state", sorted((t["state"], t["name"]) for t in threads), sorted((x["state"], x["thread"]) for x in r))
want = sorted(t["name"] for t in threads if t["state"] in ("BLOCKED", "WAITING") and t["frameCount"] > 0)
check("blocked or waiting threads (with a stack)", want, sorted(x["thread"] for x in rows(V["HeapFindingsBlockedOrWaitingThreads"])))
r = rows(V["HeapFindingsWaste"])
check("waste: bytes by headline", sorted((w["headline"], w["bytes"]) for w in waste), sorted((x["waste"], x["bytes"]) for x in r))
r = rows(V["HeapFindingsClassLoaders"])
check("class loaders: groups", sorted((g["type"], g["state"], g["instances"]) for g in loaders),
      sorted((x["loader"], x["state"], x["loaders"]) for x in r))
r = rows(V["HeapFindingsFinalization"])
check("finalization", {k: final[k] for k in ("pending", "registered", "finalized")},
      {k: r[0][k] for k in ("pending", "registered", "finalized")} if r else None)
r = rows(V["HeapFindingsDuplicateStrings"])
want = sorted(strings["groups"], key=lambda g: -g["wasted"])[:30]
check("duplicate strings: wasted bytes (top 30)", sorted(g["wasted"] for g in want), sorted(x["wastedBytes"] for x in r))
r = rows(V["HeapFindingsStringHolders"])
check("string holders", sorted((s["name"], s["overheadBytes"]) for s in strings["referrers"]),
      sorted((x["heldBy"], x["duplicationBytes"]) for x in r))
r = rows(V["HeapFindingsIdleCollections"])
want = sorted([("empty", c["className"], c["count"]) for c in collections["empty"]] +
              [("singleton", c["className"], c["count"]) for c in collections["singleton"]])
check("idle collections", want, sorted((x["shape"], x["collection"], x["count"]) for x in r))
r = rows(V["HeapFindingsHumongous"])
check("humongous arrays", sorted((h["ownerClassName"], h["totalWastedBytes"]) for h in humongous),
      sorted((x["heldBy"], x["wasted"]) for x in r))

print("== L3: cost ==")
pkg = top["packageName"]
env = invoke("HeapRetainedInCode", {"package": pkg, "jar": ""})
check("one package's retainers = jheapo's, filtered by jheapo", sorted(x["className"] for x in jheapo("/retained", n=500, package=pkg)),
      sorted(x["class"] for x in rows(env)))
n = calls(env)
print("       HeapRetainedInCode(%s) made %s source call(s)" % (pkg, n))
check("a pushed package filter costs at most one jheapo call", True, n is not None and n <= 1)
again = invoke("HeapOverviewTotals")
n = calls(again)
print("       HeapOverviewTotals, read again, made %s source call(s)" % n)
check("a repeat read is answered from the cache", 0, n)

if failures:
    print("DRIFT FOUND: %d check(s) failed" % len(failures))
    sys.exit(1)
print("ALL CHECKS PASS")

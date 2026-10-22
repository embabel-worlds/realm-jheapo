# realm-jheapo

A Java heap dump analysed by jheapo, as a graph, cross-referenced with the application's jar
(realm-java-code) and its source (realm-java-source-code). Read from jheapo's REST interface
(`bin/jheapo-rest.sh <dump.hprof>`, port 7071) when a query reaches it; nothing is copied into the
graph. That interface is not in a jheapo release yet: it is the `rest-api` branch, proposed in
[jheapo#3](https://github.com/jheapo/jheapo/pull/3).

What that buys you: one query starts at what jheapo found in the heap and ends at the line of code
responsible — the class retaining the memory, the object holding it, the field it is held in, the
method that writes that field, and the source of that method — with jheapo answering the heap half
and the jar and its source answering the code half.

## Getting started (Kirk, this is for you)

Everything below was run against a dump of jheapo analysing itself, so the queries name jheapo's
own classes. Point it at your own dump and they answer for that instead.

**Status, 23 October 2026.** Two pieces this needs are merged but not yet in a published appliance
image, and one is still a pull request:

| Needs | Where | Without it |
|---|---|---|
| jheapo's REST interface | `rest-api` branch, [jheapo#3](https://github.com/jheapo/jheapo/pull/3) | nothing to read the heap from |
| class names allowed through governance | [embabel/me#2982](https://github.com/embabel/me/pull/2982) | `className` is withheld (it contains `ssn`, which the secret-field rule took for a social security number), so every heap → code join answers nothing |
| method line tables | [embabel/me#3025](https://github.com/embabel/me/pull/3025) | only matters for the stack-frame joins in realm-jvm-logs |

Until those are released, ask Rod for an image with them in.

### 1. The appliance

```bash
embabel upgrade          # latest published image and CLI
```

`upgrade` does not touch realms; the next two steps add them.

### 2. The realms

This realm joins into three others. Clone all four side by side and link the folder:

```bash
mkdir -p ~/realms && cd ~/realms
for r in realm-jheapo realm-java-code realm-java-source-code realm-jvm-logs; do
  git clone https://github.com/embabel-worlds/$r.git
done
embabel realms link ~/realms
```

Then, from a coding agent connected to the appliance over MCP (Claude Code, say), install each by
reference — nothing is copied, so a `git pull` and `realm_refresh()` picks up changes:

```
install_realm_from_path("realm-java-code")
install_realm_from_path("realm-java-source-code")
install_realm_from_path("realm-jvm-logs")
install_realm_from_path("realm-jheapo")
```

### 3. The jar and its source

The code half reads a jar and its `-sources.jar` from your world's `data/jars`. jheapo is several
modules, so build one jar of the ones the heap's classes come from:

```bash
cd ~/dev/jheapo && mvn -q -DskipTests package
W=$(mktemp -d) && mkdir -p $W/classes $W/sources
for m in api queries ui/browser; do
  cp -R $m/target/classes/. $W/classes/
  cp -R $m/src/main/java/. $W/sources/
done
find $W/classes -type f ! -name '*.class' -delete
printf 'Implementation-Title: jheapo\nImplementation-Version: 0.1.0-SNAPSHOT\n' > $W/MANIFEST.MF
jar cfm $W/jheapo-0.1.0-SNAPSHOT.jar $W/MANIFEST.MF -C $W/classes .
jar cf  $W/jheapo-0.1.0-SNAPSHOT-sources.jar -C $W/sources .

D=/data/embabel/assistant/users/<you>/default/data/jars     # <you>: your appliance user
docker exec embabel-appliance-worlds-1 mkdir -p $D
docker cp $W/jheapo-0.1.0-SNAPSHOT.jar         embabel-appliance-worlds-1:$D/
docker cp $W/jheapo-0.1.0-SNAPSHOT-sources.jar embabel-appliance-worlds-1:$D/
```

The names matter: the keyed joins name `jars/jheapo-0.1.0-SNAPSHOT.jar` (see **Hardcoded for now**
below). Logs for realm-jvm-logs go in `data/logs` beside it, the same way.

### 4. A dump to read

```bash
cd ~/dev/jheapo && git checkout rest-api
bin/jheapo-rest.sh /path/to/dump.hprof      # page on 7070, REST on 7071
```

The appliance reaches it at `host.docker.internal:7071` (`apis/jheapo.yaml`'s `servers`). The
drill-downs — instances, holders, paths to a root — need a licensed jheapo; the analysis tabs do not.

### 5. Ask it something

Run any query below with `kg_query` over MCP, or paste it into the Worlds console's query page.
`{name: 'current'}` is the dump jheapo is serving.

## Queries, and what each one does

### How big is it?

```cypher
MATCH (h:Heap {name: 'current'})-[:HAS_OVERVIEW]->(o:HeapOverview)
RETURN o
```

jheapo's overview tab as one row: heap bytes, instances, classes, class loaders, GC roots,
duplicate-string waste, objects pending finalization. On jheapo's own dump: 134 MB, 517k instances,
3,319 classes, 1.3 MB wasted on duplicate strings. Pure heap, no code — the sanity check that the
REST connection works.

### Which packages retain the memory?

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
RETURN c.packageName AS package, sum(c.retainedBytes) / 1048576 AS retainedMB, sum(c.instances) AS instances
ORDER BY retainedMB DESC
```

jheapo's retained-classes list (the classes above its retention threshold), rolled up by package
in the query. On jheapo's dump one package, `com.kodewerk.jheapo.util`, retains 107 MB in 2,238
instances — so the next question is which class, and why.

### From each retained class to its bytecode and source file

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)-[:COMPILED_AS]->(t:JavaType)
RETURN c.className AS class, c.retainedBytes / 1048576 AS retainedMB, c.instances AS instances,
       t.kind AS kind, t.sourcePath AS source
ORDER BY retainedMB DESC
```

The first hop out of the heap. `COMPILED_AS` takes a class jheapo names to the type the jar
compiled — so a JDK class drops out here and only your own code survives. Answer:
`PrimitiveLongMap`, 107 MB, `com/kodewerk/jheapo/util/PrimitiveLongMap.java`.

### The biggest retainer → who holds it → which field → the code that fills it

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
WITH c ORDER BY c.retainedBytes DESC LIMIT 1
MATCH (c)-[:HAS_INSTANCE]->(o:HeapObject)-[:HELD_BY]->(hd:HeapHolder)-[:HELD_IN]->(f:JavaField)
MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN DISTINCT c.className AS retainer, c.retainedBytes / 1048576 AS retainedMB,
       f.key AS heldIn, f.genericType AS declared, a.method AS writer, s.text AS code
```

The whole trip in one query, and the one to show first. Hop by hop:

- `RETAINS` — jheapo's retained classes; keep the largest.
- `HAS_INSTANCE` → `HELD_BY` — its live instances, and the objects holding a reference to each
  (jheapo's drill-downs, batched 100 objects per call).
- `HELD_IN` — the holder's field that holds the reference, as the jar declares it: the switch from
  heap to bytecode.
- `ACCESSED_BY {access: 'WRITE'}` — every `putfield`/`putstatic` of that field in the jar.
- `SOURCE_AT` — the source lines around that write, from the sources jar.

On jheapo's dump `PrimitiveLongMap`'s 107 MB is held in four fields, each assigned in a
constructor: `ClassCensus$Tally.references`, `Classloaders$Tally.instancesByClass`,
`Classloaders$Tally.classByLoader` and `ClassTable.supers`.

### Who keeps adding to it?

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
WITH c ORDER BY c.retainedBytes DESC LIMIT 1
MATCH (c)-[:HAS_INSTANCE]->(:HeapObject)-[:HELD_BY]->(:HeapHolder)-[:HELD_IN]->(f:JavaField)
      -[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'READ'})-[:SAME_METHOD_CALL]->(call:JavaMethodCall)
WHERE call.calleeName IN ['put', 'add', 'putIfAbsent', 'computeIfAbsent', 'merge', 'addAll', 'putAll']
RETURN DISTINCT f.key AS field, a.method AS method, call.calleeOwner + '.' + call.calleeName AS adds, call.lines AS lines
```

A field assigned once in a constructor is not why a map is big; whatever keeps calling `put` on it
is. In bytecode, adding to a collection held in a field is a *read* of the field (`getfield`)
followed by a call on what was read, so this pairs each read of the field with a `put`/`add`-style
call in the same method. Answer: `ClassCensus$Tally.referencesOf(long)` line 212,
`Classloaders$Tally.instance(Instance)` line 213, `ClassTable.dumped(ClassDump)` line 63 — the
methods that grew the 107 MB.

### Humongous arrays → the fields that hold them → the code that sizes them

```cypher
MATCH (h:Heap {name: 'current'})-[:HUMONGOUS]->(x:HeapHumongousArray)-[:COMPILED_AS]->(t:JavaType)
      -[:DECLARES_FIELD]->(f:JavaField)
WHERE f.type ENDS WITH '[]'
MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN DISTINCT x.ownerClassName AS owner, x.instances AS arrays, x.totalWastedBytes / 1024 AS wastedKB,
       f.key AS field, f.type AS type, a.method AS writer, s.text AS code
```

jheapo's humongous finding: arrays big enough that G1 gives each its own regions, wasting the
rest of the last region. This takes the class that owns them to its array fields and the code that
assigns them. Answer: `ContentCensus` owns arrays wasting about 4 MB of region tail, through
`counts`, `hashes`, `firstOids` (`long[]`) and `contentBytes` (`int[]`), all assigned in
`ContentCensus.allocate(int)` — whose capacity doubles (`capacity <<= 1`) just above, which is how
an array crosses the humongous threshold.

### Nested collections → the field → the code that writes it

```cypher
MATCH (h:Heap {name: 'current'})-[:NESTED_COLLECTION]->(n:HeapNestedCollection)-[:HELD_IN]->(f:JavaField)
OPTIONAL MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN n.fieldKey AS field, n.storedClass AS holds, f.genericType AS declared, a.method AS writer, s.text AS code
```

jheapo flags fields holding collections of collections — a per-entry overhead that multiplies.
The finding already names the field, so it joins straight to the jar; `genericType` shows the
declared shape jheapo can only infer. Answer: `Threads$Roots.locals`, a
`Map<Integer, List<long[]>>`, and `Classloaders$Definitions.loadersByName`, a
`Map<String, Set<Long>>`, each with the constructor that builds it.

### Duplicate strings, and who holds them

```cypher
MATCH (h:Heap {name: 'current'})-[:DUPLICATE_STRING]->(d:HeapDuplicateString)
RETURN d.sample AS value, d.count AS copies, d.wasted AS wastedBytes
ORDER BY wastedBytes DESC
```

```cypher
MATCH (h:Heap {name: 'current'})-[:STRINGS_HELD_BY]->(s:HeapStringHolder)
RETURN s.name AS holder, s.objects AS strings, s.memoryBytes / 1024 AS kb, s.overheadBytes / 1024 AS wastedKB
ORDER BY wastedKB DESC
```

jheapo's strings tab, twice: the values with the most copies, then the classes and fields holding
strings, with how much of what they hold is duplication. On jheapo's own dump these are mostly the
JDK's (`Object[]`, `HashMap$Node.key`). On an application dump a holder named `Owner.field` is
your field: `MATCH (f:JavaField {id: 'jars/<jar>!Owner.field'})-[:ACCESSED_BY]->…` takes it on to
the code, as the queries above do.

### A leak suspect's path to a GC root

```cypher
MATCH (h:Heap {name: 'current'})-[:LEAK_SUSPECT]->(o:HeapObject)-[:PATH_TO_ROOT]->(p:HeapPathStep)
OPTIONAL MATCH (p)-[:COMPILED_AS]->(t:JavaType)
RETURN o.className AS suspect, p.step AS step, p.className AS class, t.sourcePath AS source
ORDER BY step
```

jheapo's leak suspects and, for each, its chain of references to a GC root. A step whose class
your jar compiled carries its `source`; the rest are the JDK's. On jheapo's own dump the suspect is
the JDK's `Cleaner` list, so `source` is empty all the way down — on a real leak, the first step
with a `source` is usually where to look.

## Views

The realm ships these as named, parameterised views (run one with `view_run`):

- `views/heap.yml` — `HeapRetainedInCode`, `HeapHoldersInCode`, `HeapFieldGrowthCode`,
  `HeapLeakPathInCode`: the queries above, generic over `jar`.
- `views/findings.yml` — one per jheapo finding: waste, duplicate strings and their holders, idle
  and nested collections, threads and blocked threads, stacks in your code, thread-local retention,
  static pins, listener leaks.
- `views/app.yml` — what `apps/heap-lens.html` calls: histogram, retainers, leak suspects, and for a
  class its instances, holders, fields, path, source and growth.
- `views/demo-jheapo-self.yml` — the demo over jheapo's dump of itself.
- `views/logs.yml` — with realm-jvm-logs: retainers whose writers appear in logged failures, and
  failing code on live thread stacks.

## Files

- `apis/jheapo.yaml`: the OpenAPI spec for jheapo's REST interface, vendored; server
  `http://host.docker.internal:7071/rest/v1`.
- `producers/heap.yml`: whole-heap producers from the `Heap` anchor, and batched walks (100 keys per
  call) with class and package filters pushed down to jheapo.
- `types/heap.yml`: HeapOverview, HeapClass, HeapObject, HeapHolder, HeapFieldValue, HeapPathStep,
  and the keyed joins into realm-java-code (COMPILED_AS → JavaType, HELD_IN → JavaField).
- `producers/findings.yml`, `types/findings.yml`: jheapo's findings tabs.

**Hardcoded for now:** the keyed joins name ONE jar, `jars/jheapo-0.1.0-SNAPSHOT.jar` under the
world's `data/` (with its `-sources.jar` beside it). The generic views take `jar` and join by name
instead, which is correct but fetches the whole jar's fields before filtering.

**Not here yet:** a class by name across the whole heap (jheapo's histogram gives the top 30, and its
retained list the classes above its threshold); retained size per object.

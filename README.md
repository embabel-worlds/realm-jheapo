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

**No application is named in this realm.** The heap half works on any dump. The code half is
whichever jar you give it: every view that reaches code takes `jar`, the application's jar as
realm-java-code reads it (e.g. `jars/app.jar` under the world's `data/`). Leave it empty and the
views answer from the heap alone.

## Getting started

### 1. The appliance

```bash
embabel upgrade          # latest published image and CLI
```

### 2. The realms

This realm joins into three others. Install them from the directory:

```
install_realm("embabel-worlds/realm-java-code")
install_realm("embabel-worlds/realm-java-source-code")
install_realm("embabel-worlds/realm-jvm-logs")        # optional: the heap read against the logs
install_realm("embabel-worlds/realm-jheapo")
```

To work on a realm instead, clone it into the folder `embabel realms link` points at and install
it by reference with `install_realm_from_path("realm-jheapo")`. Then a `realm_refresh()` picks up
every edit. See [Contributing](#contributing).

### 3. The application's code

The code half reads one jar of the application's classes, with its sources beside it as
`<name>-sources.jar`, from the world's `data/jars`. `bin/stage-app` builds both and puts them there:

```bash
bin/stage-app path/to/app.war   path/to/src/main/java          # a WAR
bin/stage-app path/to/webapp    path/to/src          myapp     # an exploded WAR (WEB-INF/classes)
bin/stage-app target/classes    src/main/java        myapp     # a build's classes folder, or a .jar
```

It takes only the application's own classes (`WEB-INF/classes`, never `WEB-INF/lib`), checks that
the source folder is the package root, and prints the value to use: `jar: "jars/myapp.jar"`.
A multi-module build: copy each module's classes into one folder first. Logs for realm-jvm-logs go
in `data/logs`.

### 4. A dump to read

```bash
cd ~/dev/jheapo && git checkout rest-api
bin/jheapo-rest.sh /path/to/dump.hprof      # page on 7070, REST on 7071
```

The appliance reaches it at `host.docker.internal:7071` (`apis/jheapo.yaml`'s `servers`; change it
there for a jheapo elsewhere). The drill-downs — instances, holders, paths to a root — need a
licensed jheapo; the analysis tabs do not.

### 5. Ask it something

Open the Heap Lens app (`apps/heap-lens.html`) and type the jar's path into **Jar**. Or run a view
with `view_run`, or any query below with `kg_query`, binding `$jar`. `{name: 'current'}` is the dump
jheapo is serving.

## How the heap meets the code

A heap row and the jar name things the same way, so they join by name with no translation:

| Heap | Jar (realm-java-code) |
|---|---|
| `HeapClass.className`, `HeapStackFrame.className` | `JavaType.name` (binary names, `pkg.Outer$Inner`) |
| `HeapObject` / `HeapHolder` / `HeapFieldValue` / `HeapPathStep` `.typeName` | `JavaType.name` |
| `HeapHolder.field`, `HeapFieldValue.fieldKey`, `HeapNestedCollection.fieldKey` | `JavaField.key` (`Owner.field`) |

`typeName` is `className` with jheapo's `class ` prefix (and ` [Sticky Class]` suffix) removed: it
names the class itself when the object is a `Class`, which is how a static field's holder appears.
`field` and `fieldKey` likewise drop jheapo's `static ` prefix.

Every query pins the jar **first** and hops from it:

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
OPTIONAL MATCH (j)-[:HAS_TYPE]->(t:JavaType {name: c.className})
```

The views write the pin as `{path: CASE WHEN $jar = '' THEN null ELSE $jar END}` so that an empty
`jar` reads no jar at all. Keep the pin first: placed after a pinned heap object, the engine does
not resolve that expression and skips the jar.

A stack frame reaches the line it was executing through a `SourceLine`, keyed the way
realm-java-code keys a member's span:

```cypher
WITH f, $jar + '!' + f.sourcePath + '#' + toString(f.line) + '#' + f.method AS lineKey
OPTIONAL MATCH (l:SourceLine {key: lineKey})-[:SOURCE_AT]->(s:SourceSpan)
```

(a constructor's frame names `<init>`; the key wants the simple class name there, as the views do).

**Cost.** A hop from the jar to a field (`HAS_FIELD {key: …}`) reads every field in the jar, and the
hops after it (`ACCESSED_BY`, `SOURCE_AT`) fetch for each, before the key narrows them. That is
quick for an application's jar. For a large library jar it is seconds, and a query that goes on to
`ACCESSED_BY` can hit realm-java-code's 5,000-record fan-out cap and be refused. Point `jar` at the
application's own code, not its dependencies.

## Leaks: a carrier, a center and its drag

A leak has three parts. The **carrier** is a collection (a map, list or array, often nested) that
keeps gaining entries. The **center** is what it carries, usually one of the application's domain
objects. The **drag** is what the center's fields keep alive. The center is the finding that
matters: the question is its lifecycle, and where that lifecycle breaks.

- `HeapLeakShape(jar, samples)`: each center with its carrier and drag. It reads the carrier off
  sampled paths to a GC root: the owner, the carrier field, and the chain of collections between
  them.
- `HeapCenterLifecycle(jar, center, carrier)`: the center's lifecycle from the jar. It covers born
  (every `new` of it), construction (what its constructors call), enrolled (each put or add given
  one, and growth of the carrier field) and released (each remove, clear or poll, and any
  reassignment of the carrier field).
- The `heap-leaks` lens (`jar`, `centers`) runs the first, then the second for each center. From
  their rows it writes a verdict: whether the center enrolls itself during construction, and
  whether any release path exists. No model is involved. Heap Lens shows it as the **Leaks** tab.

A lens is not runnable from the console or from MCP yet. Run the two views in the Query Studio,
open the Leaks tab, or call `POST /api/v1/lenses/heap-leaks/invoke` with
`{"args": {"jar": "jars/app.jar"}}`.

## What is worrying, and the code behind it

Two views put the findings in one list and take each to its code:

- `HeapConcerns` (`jar`, `minBytes`, default 1 MB): every worrying finding ranked by bytes. That
  covers wasted bytes jheapo measured, duplicated strings and the field holding them, humongous
  arrays, and leak suspects pinned by a static field. Each row names the subject (a class, or a
  field as `Owner.field`), whether it is `inApp`, and the remedy.
- `HeapConcernCode` (`jar`, `subject`): for a field, its declaration and every read and write with
  the source around each; for a class, every declaration in its source file.

`HeapAppFieldGrowth` then shows where a field grows: each `put`/`add` on a line that also reads the
field. Heap Lens shows the list as its **Concerns** tab, and a row opens its subject's code.

## Queries, and what each one does

### How big is it?

```cypher
MATCH (h:Heap {name: 'current'})-[:HAS_OVERVIEW]->(o:HeapOverview)
RETURN o
```

jheapo's overview tab as one row: heap bytes, instances, classes, class loaders, GC roots,
duplicate-string waste, objects pending finalization. Pure heap, no code: the check that the REST
connection works.

### Which packages retain the memory?

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
RETURN c.packageName AS package, sum(c.retainedBytes) / 1048576 AS retainedMB, sum(c.instances) AS instances
ORDER BY retainedMB DESC
```

jheapo's retained-classes list (the classes above its retention threshold), rolled up by package.

### From each retained class to its bytecode and source file

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
MATCH (j)-[:HAS_TYPE]->(t:JavaType {name: c.className})
OPTIONAL MATCH (t)-[:DEFINED_IN]->(s:JavaSource)
RETURN c.className AS class, c.retainedBytes / 1048576 AS retainedMB, c.instances AS instances,
       t.kind AS kind, s.path AS source
ORDER BY retainedMB DESC
```

The first hop out of the heap. A JDK or library class is not in the application's jar, so it drops
out here and only your own code survives.

### The biggest retainer → who holds it → which field → the code that fills it

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
WITH j, c ORDER BY c.retainedBytes DESC LIMIT 1
MATCH (c)-[:HAS_INSTANCE]->(o:HeapObject)-[:HELD_BY]->(hd:HeapHolder)
MATCH (j)-[:HAS_FIELD]->(f:JavaField {key: hd.field})
MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN DISTINCT c.className AS retainer, c.retainedBytes / 1048576 AS retainedMB,
       f.key AS heldIn, f.genericType AS declared, a.method AS writer, s.text AS code
```

The whole trip in one query. Hop by hop:

- `RETAINS`: jheapo's retained classes; keep the largest.
- `HAS_INSTANCE` → `HELD_BY`: its live instances, and the objects holding a reference to each
  (jheapo's drill-downs, batched 100 objects per call).
- `HAS_FIELD {key: hd.field}`: the holder's field, as the jar declares it. This is the switch from
  heap to bytecode. A static field held by a `Class` object matches too.
- `ACCESSED_BY {access: 'WRITE'}`: every `putfield`/`putstatic` of that field in the jar.
- `SOURCE_AT`: the source lines around that write, from the sources jar.

### Who keeps adding to it?

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass)
WITH j, c ORDER BY c.retainedBytes DESC LIMIT 1
MATCH (c)-[:HAS_INSTANCE]->(:HeapObject)-[:HELD_BY]->(hd:HeapHolder)
MATCH (j)-[:HAS_FIELD]->(f:JavaField {key: hd.field})
      -[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'READ'})-[:SAME_METHOD_CALL]->(call:JavaMethodCall)
WHERE call.calleeName IN ['put', 'add', 'putIfAbsent', 'computeIfAbsent', 'merge', 'addAll', 'putAll']
RETURN DISTINCT f.key AS field, a.method AS method, call.calleeOwner + '.' + call.calleeName AS adds, call.lines AS lines
```

A field assigned once in a constructor is not why a map is big; whatever keeps calling `put` on it
is. In bytecode, adding to a collection held in a field is a *read* of the field (`getfield`)
followed by a call on what was read, so this pairs each read of the field with a `put`/`add`-style
call in the same method.

### Humongous arrays → the fields that hold them → the code that sizes them

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:HUMONGOUS]->(x:HeapHumongousArray)
MATCH (j)-[:HAS_TYPE]->(t:JavaType {name: CASE WHEN x.ownerClassName STARTS WITH 'static ' THEN substring(x.ownerClassName, 7) ELSE x.ownerClassName END})
      -[:DECLARES_FIELD]->(f:JavaField)
WHERE f.type ENDS WITH '[]'
MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN DISTINCT x.ownerClassName AS owner, x.instances AS arrays, x.totalWastedBytes / 1024 AS wastedKB,
       f.key AS field, f.type AS type, a.method AS writer, s.text AS code
```

jheapo's humongous finding: arrays big enough that G1 gives each its own regions, wasting the rest of
the last region. This takes the class that owns them to its array fields and the code that assigns
them. jheapo names a statically held owner `static <class>`, hence the `CASE`.

### Nested collections → the field → the code that writes it

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:NESTED_COLLECTION]->(n:HeapNestedCollection)
OPTIONAL MATCH (j)-[:HAS_FIELD]->(f:JavaField {key: n.fieldKey})
OPTIONAL MATCH (f)-[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN n.fieldKey AS field, n.storedClass AS holds, f.genericType AS declared, a.method AS writer, s.text AS code
```

jheapo flags fields holding collections of collections, a per-entry overhead that multiplies. The
finding already names the field, so it joins straight to the jar, and `genericType` shows the
declared shape that jheapo can only infer.

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
strings, with how much of what they hold is duplication. A holder named `Owner.field` is a field:
`MATCH (j:Jar {path: $jar})-[:HAS_FIELD]->(f:JavaField {key: 'Owner.field'})-[:ACCESSED_BY]->…`
takes it on to the code.

### A leak suspect's path to a GC root

```cypher
OPTIONAL MATCH (j:Jar {path: $jar})
MATCH (h:Heap {name: 'current'})-[:LEAK_SUSPECT]->(o:HeapObject)-[:PATH_TO_ROOT]->(p:HeapPathStep)
OPTIONAL MATCH (j)-[:HAS_TYPE]->(t:JavaType {name: p.typeName})
OPTIONAL MATCH (t)-[:DEFINED_IN]->(s:JavaSource)
RETURN o.className AS suspect, p.step AS step, p.className AS class, s.path AS source
ORDER BY step
```

jheapo's leak suspects and, for each, its chain of references to a GC root. A step whose class your
jar compiled carries its `source`; the rest are the JDK's or a library's. On a real leak, the first
step with a `source` is usually where to look.

## Views

The realm ships these as named, parameterised views (run one with `view_run`). Each that reaches
code takes `jar` (empty: the heap alone):

- `views/heap.yml`: `HeapRetainedInCode`, `HeapHoldersInCode`, `HeapFieldGrowthCode`,
  `HeapLeakPathInCode`, which are the queries above.
- `views/findings.yml`: one per jheapo finding. Waste, duplicate strings and their holders, idle and
  nested collections, threads and blocked threads, stacks in your code, thread-local retention,
  static pins, listener leaks, identity-hashed keys, class loaders, humongous arrays, entanglement,
  finalization.
- `views/app.yml`: what `apps/heap-lens.html` calls. Histogram, retainers, leak suspects, and for a
  class its instances, holders, fields, path, source and growth.
- `views/concerns.yml`: `HeapConcerns` and `HeapConcernCode`, above.
- `views/leaks.yml`: `HeapLeakShape` and `HeapCenterLifecycle`, above.
- `views/logs.yml`: with realm-jvm-logs, the retainers whose writers appear in logged failures, and
  failing code on live thread stacks.

The `heap-takeaways` lens reads the views and has a model write up the dump. It takes `jar` too.
The `heap-leaks` lens composes the two leak views into one report per center, with a verdict.

## Files

- `apis/jheapo.yaml`: the OpenAPI spec for jheapo's REST interface, vendored; server
  `http://host.docker.internal:7071/rest/v1`.
- `producers/heap.yml`: whole-heap producers from the `Heap` anchor, and batched walks (100 keys per
  call) with class and package filters pushed down to jheapo.
- `types/heap.yml`: HeapOverview, HeapClass, HeapObject, HeapHolder, HeapFieldValue, HeapPathStep.
- `producers/findings.yml`, `types/findings.yml`: jheapo's findings tabs, and the `SourceLine`
  anchor that takes a stack frame to its source.

**Not here yet:** a class by name across the whole heap (jheapo's histogram gives the top 30, and its
retained list the classes above its threshold); retained size per object.

## Contributing

Changes come as pull requests from a fork:

1. Fork `embabel-worlds/realm-jheapo` and clone your fork into the folder `embabel realms link`
   points at.
2. `install_realm_from_path("realm-jheapo")`, once. The world now reads your checkout.
3. Edit, then `realm_validate_path("realm-jheapo")` and `realm_refresh()`. Check the change by
   running the views it touches against a real dump (`view_run`, `kg_query`): rows back, not just
   a green status.
4. Push a branch to your fork and open a PR against `embabel-worlds/realm-jheapo`. Say which dump
   and jar you tested against.

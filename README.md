# realm-jheapo

A Java heap dump analysed by jheapo, as a graph, cross-referenced with the application's jar
(realm-java-code) and its source (realm-java-source-code). Read from jheapo's REST interface
(`bin/jheapo-rest.sh <dump.hprof>`, port 7071) when a query reaches it; nothing is copied into the
graph. That interface is not in a jheapo release yet: it is the `rest-api` branch, proposed in
[jheapo#3](https://github.com/jheapo/jheapo/pull/3).

```cypher
MATCH (h:Heap {name: 'current'})-[:RETAINS]->(c:HeapClass {className: 'com.kodewerk.jheapo.util.PrimitiveLongMap'})
      -[:HAS_INSTANCE]->(o:HeapObject)-[:HELD_BY]->(hd:HeapHolder)-[:HELD_IN]->(f:JavaField)
      -[:ACCESSED_BY]->(a:JavaFieldAccess {access: 'WRITE'})-[:SOURCE_AT]->(s:SourceSpan)
RETURN f.key, a.method, s.text
```

- `apis/jheapo.yaml`: the OpenAPI spec for jheapo's REST interface, vendored; server
  `http://host.docker.internal:7071/rest/v1`.
- `producers/heap.yml`: whole-heap producers from the `Heap` anchor, and batched walks (100 keys per
  call) with class and package filters pushed down to jheapo.
- `types/heap.yml`: HeapOverview, HeapClass, HeapObject, HeapHolder, HeapFieldValue, HeapPathStep,
  and the keyed joins into realm-java-code (COMPILED_AS → JavaType, HELD_IN → JavaField).
- `views/`: generic views taking `jar`, and demo views over jheapo's dump of itself.

**Hardcoded for now:** the keyed joins name ONE jar, `jars/jheapo-0.1.0-SNAPSHOT.jar` under the
world's `data/` (with its `-sources.jar` beside it). The generic views take `jar` and join by name
instead, which is correct but fetches the whole jar's fields before filtering.

**Not here yet:** a class by name across the whole heap (jheapo's histogram gives the top 30, and its
retained list the classes above its threshold); retained size per object.

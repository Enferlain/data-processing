# Tasks

## 1. Adapter emission

- [x] 1.1 Post item emits description content as `text` (presence bool kept); non-string fails
      closed
- [x] 1.2 Media occurrence carries `duration_ms` from the top-level seconds float; malformed
      values fail closed
- [x] 1.3 `sample.alternates` URL-bearing entries enrich the variants under `alternate:*`
      names with dims/ext/mime/fps/codec; existing roles unchanged

## 2. Fixtures and tests

- [x] 2.1 e621 fixtures gain description content, duration, and alternates evidence
- [x] 2.2 Adapter tests pin the new emission; sync tests prove persistence into text_content,
      duration_ms, and variants_json

## 3. Spec and docs

- [x] 3.1 Delta modifies the nested-facts requirement; strict validation passes
- [x] 3.2 Audit rows updated (description/duration/alternates normalized; locked_tags/
      change_seq raw; sets verification result recorded); CHANGELOG
- [x] 3.3 Full gates green; archive

# Raw examination of goals

"Yeah — I think **“media catalog” is becoming too narrow a description of what this wants to be**.

What you’re describing is closer to a **source-aware data gathering + provenance/bookkeeping system**. Media is an excellent first domain because the relationships are messy enough to force the architecture to be good, but the underlying capability is much broader.

The important object isn't really “an image in my collection.” It's:

> **A piece of information or content was observed somewhere, at some time, through some source, with some metadata. Preserve that observation, connect it to other observations where justified, and never lose where any fact came from.**

That changes the framing quite a lot.

### The core thing you have isn't a catalog

It's basically:

```text
source
  ↓
fetch / import / observe
  ↓
raw observation
  ↓
normalized facts
  ↓
entities / artifacts / representations
  ↓
relationships + evidence
  ↓
reviewed or derived conclusions
  ↓
arbitrary projections / datasets / exports
```

And **none of those layers inherently care whether the payload is an image**.

It could be:

- image
- animation
- video
- audio
- text
- webpage
- post
- profile
- file/archive
- model
- dataset record
- metadata document
- some weird future object a provider exposes

The content-specific parts come later.

---

Your five-version example is exactly why this becomes useful.

Imagine one artwork appearing as:

```text
Pixiv
  original PNG
      │
      ├─ Twitter JPEG recompression
      │      └─ reposted unchanged on website A
      │
      ├─ censored Pixiv variant
      │
      ├─ cropped version on booru B
      │
      └─ edited text version on booru C
```

Those aren't five records you want to collapse into one.

They're **five separately observed objects with their own provenance and metadata**, plus evidence-backed relationships between them.

You could know:

```text
A and B       exact same bytes
B and C       same pixels, different container metadata
A and D       probable resize/recompression
A and E       crop of
A and F       censored variant of
A and G       edit of
G and H       exact same bytes, observed on another site
```

And independently:

```text
A observed on Pixiv at time X
H observed on Gelbooru at time Y
Gelbooru says artist tag Z
Pixiv says account ID Q uploaded A
source URL on H points to A
local SHA-256 confirms G == H
reviewer confirmed A/G are variants of one underlying work
```

That distinction is **massively more useful than merely having a folder of files**.

### And for training data this gets particularly valuable

Instead of assembling:

```text
/images/
    001.png
    002.jpg
    003.webp
```

you could ask the system for something like:

> Give me all locally acquired visual representations matching these criteria, group near-duplicate/variant families, exclude thumbnails, prefer upstream originals, retain censored and uncensored variants as distinct samples, include source provenance and tags, and export the result into schema X.

Or:

> Find every representation of these 20,000 works, but don't accidentally count Twitter recompressions and exact booru mirrors as three independent examples.

Or:

> Show me every case where two providers disagree on artist attribution.

Or:

> Build a training set using the richest metadata available across all observations, while retaining exactly which source supplied each field.

That's **data engineering**, not really media-library management.

---

## I'd generalize the conceptual model

I wouldn't try to make everything one generic `thing` table with arbitrary key/value pairs. That tends to turn into EAV soup.

Instead I'd make a **small generic provenance kernel**, with typed domain schemas layered over it.

Something roughly like:

```text
Source
  provider / local import / file / API / webpage / etc.

SourceObject
  stable provider-native object identity

Observation
  what source X reported about object Y at time Z
  + raw retained response

Artifact
  a concrete content-bearing thing

Blob
  exact bytes, hashes, size, MIME

Representation
  one representation of an artifact/content object

Assertion
  "source X says property P = value V"

Relationship
  X --relationship--> Y

Evidence
  why we believe that relationship/assertion

Acquisition
  how bytes entered local storage

Run
  import/fetch/crawl/analysis operation and its limits/version
```

Then media can add its own vocabulary:

```text
dimensions
duration
frames
codec
sample rate
channels
pixel fingerprint
audio fingerprint
video fingerprint
```

Training-data tooling can add:

```text
caption
labels
dataset membership
quality assessment
annotation
split
transformation history
model-derived features
```

Social sources add:

```text
account
post
reply
repost
favorite
bookmark
author/uploader/etc.
```

The generic core doesn't have to know all of those.

### Relationships become a first-class asset

This might actually become one of the most valuable parts of the whole thing.

Instead of only storing “matches,” make relationships typed and provenance-bearing:

```text
same_bytes
same_content
reencoded_from
resized_from
cropped_from
transcoded_from
censored_variant_of
uncensored_variant_of
edited_from
translated_variant_of
thumbnail_of
preview_of
page_of
extracted_from
reposted_from
derived_from
probably_same_work
confirmed_same_work
```

And importantly, don't force every relationship to mean the same epistemic thing.

You can distinguish:

```text
observed
    provider explicitly says X is source of Y

verified
    hashes prove X and Y have identical bytes

derived
    deterministic algorithm establishes relationship

inferred
    matcher proposes X probably relates to Y

reviewed
    human accepted/rejected that conclusion
```

That fits the philosophy already present in the repo **extremely well**.

---

## The “build your own schema” part is also important

I'd make the durable database the **evidence/provenance layer**, not necessarily the final schema people consume.

Then views/exporters can create whatever representation a particular job wants:

```text
raw observations
        │
        ├──> training dataset schema
        ├──> media-library view
        ├──> artist/work view
        ├──> source archive
        ├──> parquet/jsonl
        ├──> research table
        └──> some future application's schema
```

That means the system doesn't have to predict every downstream use.

It primarily guarantees:

> **I can tell you what we know, where it came from, what is directly observed versus inferred, and how objects relate.**

Then projection is cheap.

That's a much stronger long-term architecture.

---

There is one slight tweak I'd make to “there's zero downside to knowing more.”

Conceptually I agree with the intent, but mechanically there *are* costs: storage, noisy/stale observations, privacy, conflicting facts, expensive extraction, schema complexity.

The solution shouldn't be **discard information**, though. It should be:

> preserve information cheaply and faithfully, but don't force all retained information into the current canonical interpretation.

Which is already what your raw-observation model is doing.

You can have 15 sources disagree and simply retain:

```text
source A asserted x
source B asserted y
source C omitted the field
local verification found z
current projection currently chooses z
```

Nothing had to be destroyed to produce a usable current view.

That's a very good property for research/data gathering because your interpretation can improve later.

---

### So I'd change the project's north star

Not:

> Build a cross-platform media catalog.

More like:

> **Build a local-first system for gathering, retaining, cross-referencing, verifying, and organizing data from heterogeneous sources while preserving provenance and uncertainty.**

Media then becomes the first major data family rather than the definition of the system.

And the current repo is actually surprisingly close to having the right bones for that already. The parts I'd generalize first aren't the Pixiv/Gelbooru adapters—they can stay domain-specific. I'd look at the concepts currently named around **catalog, post, media occurrence, artist-library expansion, and matching**, determine which are genuinely media concepts versus generic provenance/job/evidence concepts, and establish the generic layer underneath them.

That would also change what I'd pick as the next milestone. I probably **wouldn't jump straight into the work/image-version model now**. I'd first do an architectural pass specifically asking:

> *What is the smallest domain-neutral provenance/data-gathering core already latent in the repository, and which current media-specific assumptions prevent other data types and arbitrary source-derived schemas from using it?*

That could give you a much better foundation before another couple of months of features accidentally bake “media catalog” into every level of the system."

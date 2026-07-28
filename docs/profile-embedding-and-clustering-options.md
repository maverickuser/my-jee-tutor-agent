# Profile Embedding and Clustering

## Purpose

This document explains how the `profile` task converts question-level diagnosis
evidence into conceptual clusters. It also records the previous implementation
and the alternatives considered.

The scope is intentionally limited to:

1. What information is embedded.
2. How similar questions become candidate clusters.
3. How those candidates could be improved.

Report generation and the `diagnosis` task are outside this document.

## Implemented Process

The pipeline has four stages:

```text
Question diagnosis evidence
          |
          v
Create one embedding per question
          |
          v
Retrieve mutual top-k candidate pairs
          |
          v
Gemini classifies pairs and synthesizes strands
          |
          v
Keep recurring strands supported by at least two reports
```

### 1. Question evidence

Every diagnosed wrong question becomes one evidence record containing:

- Subject
- Chapter
- Topic
- Exact concept gap
- Likely student thought
- Why that thought is wrong
- Deep-dive recommendation
- Question, test, and diagnosis report identifiers

### 2. Embedding input

One 256-dimensional `gemini/gemini-embedding-2` vector is created for each
question. Input version `v2` embeds only:

```text
Exact concept gap: ...
Likely student thought: ...
Why wrong: ...
```

Subject remains the profile scope, chapter family remains the retrieval
boundary, and topic plus deep-dive recommendation remain available to Gemini.
Embeddings are cached in DynamoDB. A cached vector is reused when the evidence
text, embedding model, and input version have not changed.

### 3. Chapter-family boundary

Before comparing embeddings, evidence is divided into normalized chapter
families.

For example:

```text
Electrostatics
Electrostatics and Capacitance
Capacitance
            |
            v
Electrostatics and Capacitance
```

Only evidence inside the same chapter family participates in the first
clustering stage. Evidence from Current Electricity cannot enter an
Electrostatics candidate cluster.

### 4. Mutual-neighbour retrieval and adjudication

Within each chapter family, the system:

1. Calculates cosine similarity for every pair of question embeddings.
2. Ranks each item's neighbours by similarity, breaking ties by evidence ID.
3. Retains a pair only when similarity is at least `0.68` and both items rank
   each other in their top three neighbours.
4. Sends the explicit candidate pairs to Gemini.

Example:

```text
A ------ 0.72 ------ B ------ 0.70 ------ C

A-to-C similarity = 0.40
```

Unlike the previous connected-component algorithm, a bridge does not
automatically make A, B, and C one candidate group. Gemini must classify every
retrieved pair exactly once as:

- `same_underlying_gap`
- `related_but_distinct`
- `unrelated`
- `non_conceptual`

A multi-question strand is accepted only when its members are connected by
`same_underlying_gap` decisions and no internal retrieved pair has a
conflicting label. Missing, duplicate, or invented pair decisions are rejected.

Finally, a conceptual strand is considered longitudinally recurring only when
it has medium or high confidence and evidence from at least two independent
diagnosis reports.

## Strengths of the Implemented Approach

- Focused embeddings represent the diagnosed misconception instead of metadata
  or remediation language.
- Chapter-family boundaries prevent arbitrary subject-wide clustering.
- Reciprocal neighbours reduce accidental bridge relationships.
- Pair candidates are only retrieval results; Gemini makes the semantic
  decision explicitly.
- Recurrence is based on independent reports, not question count.
- Deterministic validation enforces pair coverage, relationship consistency,
  evidence identifiers, and chapter-family boundaries.
- Cached embeddings avoid repeated model calls for unchanged evidence.

## Remaining Limitations

### Hand-written chapter normalization

Chapter-family normalization currently depends on a small set of explicit
rules. It is not a complete taxonomy-driven mapping across all JEE subjects.

### Uncalibrated retrieval defaults

The `0.68` similarity floor and top-three-neighbour limit are code defaults.
They have not been selected from a labelled misconception dataset.

## Embedding Options

### Option A: Legacy combined vector

Embed all seven fields in one vector.

**Advantages**

- Simple.
- Contains rich context.
- Requires one vector per question.

**Disadvantages**

- Context can dominate the underlying misconception.
- It is difficult to explain why two questions matched.
- Recommendation language can introduce false similarity.

### Option B: Focused conceptual vector

Embed only:

```text
Underlying concept gap
Student's incorrect mental model
Why that model fails
```

Keep subject and chapter as deterministic filters. Give topic and
recommendation to the Gemini classifier as context, but do not include them in
the similarity vector.

**Advantages**

- Closely aligned with the clustering objective.
- Reduces similarity caused by syllabus labels or generic recommendations.
- Retains one vector per question.

**Disadvantages**

- May lose context needed to distinguish short or ambiguous diagnoses.

### Option C: Canonical misconception statement

First ask an LLM to create a concise normalized misconception statement. Embed
that statement instead of the original fields.

**Advantages**

- Produces a clean semantic target.
- Can normalize varied diagnosis wording.

**Disadvantages**

- Adds an LLM call.
- The normalization step can remove nuance or invent an interpretation.
- Requires storing and validating the canonical statement.

### Option D: Multiple field-specific vectors

Create separate vectors:

```text
Concept vector:
  exact concept gap + likely thought + why wrong

Context vector:
  chapter + topic + recommendation
```

Calculate a weighted similarity:

```text
combined similarity =
    0.80 * concept similarity
  + 0.20 * context similarity
```

**Advantages**

- Makes field importance explicit.
- Allows separate inspection of conceptual and contextual similarity.

**Disadvantages**

- Requires more storage and model calls.
- Weights must be calibrated against labelled evidence.

### Option E: No embeddings

Ask an LLM to compare every possible question pair.

**Advantages**

- Direct semantic judgement.

**Disadvantages**

- Expensive.
- Quadratic number of comparisons.
- Harder to operate as history grows.

## Clustering Options

### Option 1: Connected components

This was the previous approach.

Any path of similar items creates one candidate group.

**Best property:** candidate recall.

**Main risk:** chaining can create overly broad candidates.

### Option 2: Complete-link hierarchical clustering

Merge two groups only when every item in one group is sufficiently similar to
every item in the other.

```text
A similar to B
B similar to C
A not similar to C

Result: do not merge all three
```

**Advantages**

- Produces cohesive candidates.
- Prevents chaining.

**Disadvantages**

- May split valid conceptual strands whose manifestations look very different.

### Option 3: Average-link hierarchical clustering

Merge groups according to their average cross-group similarity.

**Advantages**

- Balances cohesion and recall.
- Less vulnerable to chaining than connected components.

**Disadvantages**

- Still requires a calibrated threshold.

### Option 4: DBSCAN or HDBSCAN

Identify dense groups and leave isolated items as noise.

**Advantages**

- Naturally represents isolated evidence.
- Does not require choosing the number of clusters.

**Disadvantages**

- Often unstable with small student histories.
- Requires density and distance tuning.

### Option 5: Mutual top-k neighbour graph

Connect A and B only when:

```text
similarity is above the threshold
and
A is one of B's top-k neighbours
and
B is one of A's top-k neighbours
```

**Advantages**

- Removes many accidental bridge edges.
- Preserves close semantic neighbours.
- Scales better as history grows.

**Disadvantages**

- Adds a `k` parameter that must be calibrated.

### Option 6: LLM-adjudicated pair graph

Use embeddings to retrieve likely neighbours. Ask Gemini to classify each
candidate pair:

```text
same underlying gap
related but distinct
unrelated
non-conceptual
```

Only `same underlying gap` creates a clustering edge.

**Advantages**

- Strong semantic precision.
- Pair-level decisions are auditable.

**Disadvantages**

- Requires more LLM work.
- Pair judgements can be inconsistent.
- Batching is needed to control cost.

## Implemented Direction

The implemented design is:

```text
Question evidence
        |
        v
Focused conceptual embedding
(gap + thought + why wrong)
        |
        v
Hard subject boundary
Normalized chapter-family boundary
        |
        v
Mutual top-k similar neighbours
        |
        v
Gemini pair classification and strand synthesis
        |
        v
Validated conceptual strands
```

Specifically, the implementation:

1. Removes subject, chapter, topic, and recommendation from embedding text.
2. Continues using subject as the hard profile scope.
3. Retains normalized chapter family as the candidate boundary.
4. Uses mutual top-three neighbours with a `0.68` absolute similarity floor.
5. Requires Gemini to classify every candidate pair explicitly.
6. Keeps Gemini as the final semantic adjudicator.
7. Retains the rule that recurrence requires evidence from at least two reports.

This preserves the current system's high recall and evidence controls while
reducing similarity caused by shared metadata and recommendation language.

## Evaluation Plan

Thresholds and clustering parameters should be selected from labelled
diagnosis evidence rather than intuition.

Create a dataset of question pairs labelled as:

```text
same underlying misconception
related but distinct
unrelated
non-conceptual
```

Also provide expected cluster membership for representative multi-paper
student histories.

Compare each embedding and clustering option using:

- **Candidate recall:** how many genuinely related pairs reach Gemini?
- **Candidate precision:** how much unrelated evidence reaches Gemini?
- **Final strand precision:** how often does the system report a false
  recurring gap?
- **Final strand recall:** how many known recurring gaps are recovered?
- **Largest candidate size:** does chaining create oversized candidates?
- **Stability:** do paraphrased diagnoses produce the same cluster?
- **Cost and latency:** how many embedding and LLM calls are required?

The target should prioritize:

1. High candidate recall, because missed candidates cannot be recovered later.
2. Very high final-strand precision, because a false longitudinal claim can
   mislead students and teachers.

## Decision Summary

The implemented design embeds only the conceptual diagnosis, retrieves
reciprocal local neighbours instead of connected components, requires Gemini
to label each relationship, and deterministically rejects unsupported strands.
